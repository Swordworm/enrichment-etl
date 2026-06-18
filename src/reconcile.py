import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from slugify import slugify
from sqlalchemy import insert, update
from tqdm import tqdm

logger = logging.getLogger(__name__)

from src.db import canonical, engine


def _val(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    return None if s.lower() in ("null", "nan", "none", "") else s


def _normalize_domain(domain) -> str | None:
    d = _val(domain)
    if not d:
        return None
    d = d.lower()
    return d[4:] if d.startswith("www.") else d


def _fuzzy_name_match(
    name: str, canonical_df: pd.DataFrame, threshold: float = 0.85
) -> pd.Series | None:
    if not name:
        return None
    name_lower = name.lower().strip()
    best_ratio, best_row = 0.0, None
    for _, row in canonical_df.iterrows():
        cn = _val(row.get("name"))
        if not cn:
            continue
        ratio = SequenceMatcher(None, name_lower, cn.lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best_row = ratio, row
    return best_row if best_ratio >= threshold else None


def _find_match(row: pd.Series, canonical_df: pd.DataFrame) -> pd.Series | None:
    # 1. crunchbase slug
    cb_slug = _val(row.get("crunchbase"))
    if cb_slug:
        m = canonical_df[canonical_df["crunchbase"] == cb_slug]
        if not m.empty:
            return m.iloc[0]
    # 2. domain
    dom = _normalize_domain(row.get("domain"))
    if dom:
        m = canonical_df[canonical_df["domain"].apply(_normalize_domain) == dom]
        if not m.empty:
            return m.iloc[0]
    # 3. linkedin handle
    li_handle = _val(row.get("linkedin"))
    if li_handle:
        m = canonical_df[canonical_df["linkedin"] == li_handle]
        if not m.empty:
            return m.iloc[0]
    # 4. pitchbook URL
    pb = _val(row.get("pitchbook"))
    if pb:
        m = canonical_df[canonical_df["pitchbook"] == pb]
        if not m.empty:
            return m.iloc[0]
    # 5. fuzzy name fallback
    return _fuzzy_name_match(str(row.get("name", "")), canonical_df)


def _build_updates(
    row: pd.Series,
    matched: pd.Series,
    cb: dict | None,
    li: dict | None,
    cb_loc: dict | None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    updates: dict = {"updated_at": now}
    curr = {k: _val(v) for k, v in matched.items()}

    def fill_null(field: str, value) -> None:
        v = _val(value)
        if v and not curr.get(field):
            updates[field] = v

    # dynamic — always overwrite if CB/LI has value
    if cb:
        if _val(cb.get("operating_status")):
            updates["operating_status"] = _val(cb["operating_status"])
        if _val(cb.get("employee_count_range")):
            updates["num_employees"] = _val(cb["employee_count_range"])
        if _val(cb.get("short_description")):
            updates["short_description"] = _val(cb["short_description"])
        if _val(cb.get("acquired_by")):
            updates["acquired"] = _val(cb["acquired_by"])

    # short_description: LI fallback
    if "short_description" not in updates and li and _val(li.get("about")):
        updates["short_description"] = _val(li["about"])

    # static — fill null only
    if cb:
        fill_null("company_type", cb.get("company_type"))
        fill_null("ipo_status", cb.get("ipo_status"))
        fill_null("contact_email", cb.get("contact_email"))
        fill_null("contact_phone", cb.get("contact_phone"))
    if cb_loc:
        fill_null("address", cb_loc.get("address"))
    if li and _val(li.get("founded_year")):
        fill_null("founded_date", f"{int(float(li['founded_year']))}-01-01 00:00:00")

    # identifiers — fill null only from input row
    for field in ("crunchbase", "domain", "linkedin", "pitchbook", "twitter"):
        fill_null(field, row.get(field))

    return updates


def _build_new_record(
    row: pd.Series,
    cb: dict | None,
    li: dict | None,
    cb_loc: dict | None,
    existing_perms: set,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    name = _val(row.get("name")) or ""
    base = slugify(name) or "unknown"
    perm, i = base, 1
    while perm in existing_perms:
        perm = f"{base}-{i}"
        i += 1
    existing_perms.add(perm)

    record: dict = {
        "guru_permalink": perm,
        "name": name,
        "created_at": now,
        "updated_at": now,
    }
    for field in ("crunchbase", "domain", "linkedin", "pitchbook", "twitter"):
        record[field] = _val(row.get(field))

    if cb:
        record.update({
            "operating_status": _val(cb.get("operating_status")),
            "company_type": _val(cb.get("company_type")),
            "num_employees": _val(cb.get("employee_count_range")),
            "short_description": _val(cb.get("short_description")),
            "ipo_status": _val(cb.get("ipo_status")),
            "contact_email": _val(cb.get("contact_email")),
            "contact_phone": _val(cb.get("contact_phone")),
            "acquired": _val(cb.get("acquired_by")),
        })
    if cb_loc:
        record["address"] = _val(cb_loc.get("address"))
    if not record.get("short_description") and li and _val(li.get("about")):
        record["short_description"] = _val(li["about"])
    if li and _val(li.get("founded_year")):
        record["founded_date"] = f"{int(float(li['founded_year']))}-01-01 00:00:00"

    return record


def reconcile_all() -> None:
    with engine.connect() as conn:
        input_df = pd.read_sql("SELECT * FROM input_companies", conn)
        canonical_df = pd.read_sql("SELECT * FROM canonical", conn)
        cb_df = pd.read_sql("SELECT * FROM cb_companies", conn)
        cb_loc_df = pd.read_sql("SELECT * FROM cb_locations", conn)
        li_df = pd.read_sql("SELECT * FROM li_companies", conn)

    existing_perms: set = set(canonical_df["guru_permalink"].dropna().tolist())

    for _, row in tqdm(input_df.iterrows(), total=len(input_df), desc="Reconciling"):
        cb_slug = _val(row.get("crunchbase"))
        li_handle = _val(row.get("linkedin"))

        cb_rows = cb_df[cb_df["permalink"] == cb_slug] if cb_slug else pd.DataFrame()
        cb = cb_rows.iloc[0].to_dict() if not cb_rows.empty else None

        cb_loc_rows = (
            cb_loc_df[cb_loc_df["permalink"] == cb_slug] if cb_slug else pd.DataFrame()
        )
        cb_loc = cb_loc_rows.iloc[0].to_dict() if not cb_loc_rows.empty else None

        li_rows = li_df[li_df["handle"] == li_handle] if li_handle else pd.DataFrame()
        li = li_rows.iloc[0].to_dict() if not li_rows.empty else None

        matched = _find_match(row, canonical_df)

        with engine.connect() as conn:
            if matched is not None:
                updates = _build_updates(row, matched, cb, li, cb_loc)
                conn.execute(
                    update(canonical)
                    .where(canonical.c.guru_permalink == matched["guru_permalink"])
                    .values(**updates)
                )
            else:
                record = _build_new_record(row, cb, li, cb_loc, existing_perms)
                conn.execute(insert(canonical).values(**record))
            conn.commit()

    _export_csv()


def _export_csv() -> None:
    out_dir = Path(__file__).parent.parent / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM canonical", conn)
    df.to_csv(out_dir / "canonical.csv", index=False)
    logger.info("Exported %d records to data/output/canonical.csv", len(df))
