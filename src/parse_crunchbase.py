import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, insert

from src.db import cb_categories, cb_companies, cb_funding_rounds, cb_locations, engine

_RAW_DIR = Path(__file__).parent.parent / "data" / "raw"


def parse_all() -> None:
    for path in sorted(_RAW_DIR.glob("*_crunchbase.json")):
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
        for record in records:
            if "error" in record:
                continue
            _parse_record(record)


def _parse_record(r: dict) -> None:
    permalink = r.get("id") or r.get("company_id")
    if not permalink:
        return

    enriched_at = datetime.now(timezone.utc).isoformat()
    rounds = r.get("funding_rounds_list") or []
    last_funding_type = rounds[-1].get("title") if rounds else None

    acquired_by_obj = r.get("acquired_by")
    if isinstance(acquired_by_obj, dict):
        acquired_by = acquired_by_obj.get("acquirer") or json.dumps(acquired_by_obj)
    else:
        acquired_by = None

    with engine.connect() as conn:
        conn.execute(delete(cb_companies).where(cb_companies.c.permalink == permalink))
        conn.execute(
            insert(cb_companies).values(
                permalink=permalink,
                name=r.get("name"),
                short_description=r.get("about"),
                full_description=r.get("full_description"),
                website=r.get("website"),
                operating_status=r.get("operating_status"),
                company_type=r.get("company_type"),
                employee_count_range=r.get("num_employees"),
                total_funding_usd=r.get("funds_total"),
                ipo_status=r.get("ipo_status"),
                last_funding_type=last_funding_type,
                contact_email=r.get("email_address"),
                contact_phone=r.get("phone_number"),
                acquired_by=acquired_by,
                social_media_links=json.dumps(r.get("social_media_links") or []),
                enriched_at=enriched_at,
            )
        )

        conn.execute(delete(cb_categories).where(cb_categories.c.permalink == permalink))
        for ind in (r.get("industries") or []):
            conn.execute(
                insert(cb_categories).values(
                    permalink=permalink,
                    category_name=ind.get("value"),
                    category_slug=ind.get("id"),
                )
            )

        conn.execute(delete(cb_locations).where(cb_locations.c.permalink == permalink))
        loc = r.get("location") or []
        conn.execute(
            insert(cb_locations).values(
                permalink=permalink,
                city=loc[0].get("name") if len(loc) > 0 else None,
                state=loc[1].get("name") if len(loc) > 1 else None,
                country=loc[2].get("name") if len(loc) > 2 else None,
                continent=loc[3].get("name") if len(loc) > 3 else None,
                country_code=r.get("country_code"),
                address=r.get("address"),
            )
        )

        conn.execute(
            delete(cb_funding_rounds).where(cb_funding_rounds.c.permalink == permalink)
        )
        for rnd in rounds:
            money = rnd.get("money_raised") or {}
            conn.execute(
                insert(cb_funding_rounds).values(
                    permalink=permalink,
                    round_id=rnd.get("id"),
                    round_uuid=rnd.get("uuid"),
                    title=rnd.get("title"),
                    raised_amount_usd=money.get("value_usd"),
                    lead_investors=json.dumps(rnd.get("lead_investors") or []),
                )
            )

        conn.commit()
