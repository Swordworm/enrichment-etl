import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, insert
from tqdm import tqdm

from src.db import engine, li_companies, li_locations

_RAW_DIR = Path(__file__).parent.parent / "data" / "raw"


def parse_all() -> None:
    for path in tqdm(sorted(_RAW_DIR.glob("*_linkedin.json")), desc="Parsing LI"):
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
        if isinstance(records, dict):
            records = [records]
        for record in records:
            if "error" in record:
                continue
            _parse_record(record)


def _parse_record(r: dict) -> None:
    handle = r.get("id")
    if not handle:
        return

    enriched_at = datetime.now(timezone.utc).isoformat()

    with engine.connect() as conn:
        conn.execute(delete(li_companies).where(li_companies.c.handle == handle))
        conn.execute(
            insert(li_companies).values(
                handle=handle,
                company_id=r.get("company_id"),
                name=r.get("name"),
                website=r.get("website"),
                about=r.get("about"),
                employee_count=r.get("employees_in_linkedin"),
                company_size=r.get("company_size"),
                founded_year=r.get("founded"),
                organization_type=r.get("organization_type"),
                industries=r.get("industries"),
                specialties=r.get("specialties"),
                headquarters=r.get("headquarters"),
                country_code=r.get("country_code"),
                slogan=r.get("slogan"),
                url=r.get("url"),
                enriched_at=enriched_at,
            )
        )

        conn.execute(delete(li_locations).where(li_locations.c.handle == handle))
        # prefer formatted_locations (cleaner strings), fall back to locations
        locations = r.get("formatted_locations") or r.get("locations") or []
        for loc in locations:
            if loc:
                conn.execute(insert(li_locations).values(handle=handle, location=str(loc)))

        conn.commit()
