import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import httpx
import pandas as pd
from slugify import slugify
from sqlalchemy import insert
from tenacity import retry, stop_after_attempt, wait_exponential

from src.brightdata import scrape_one
from src.config import config
from src.db import engine, enrichment_log

_RAW_DIR = Path(__file__).parent.parent / "data" / "raw"


def has_identifier(val) -> bool:
    # xlsx empty cells = NaN; defensive check also handles literal "null" strings
    return pd.notna(val) and str(val).strip().lower() != "null"


def _build_url(row: pd.Series, source: str) -> str:
    if source == "crunchbase":
        return f"https://www.crunchbase.com/organization/{row['crunchbase']}"
    return f"https://www.linkedin.com/company/{row['linkedin']}"


def _log_status(company: str, source: str, status: str, error: str | None = None) -> None:
    with engine.connect() as conn:
        conn.execute(
            insert(enrichment_log).values(
                company=company,
                source=source,
                status=status,
                error=error,
                logged_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        conn.commit()


async def _save_raw(company_name: str, source: str, data: list) -> None:
    slug = slugify(company_name)
    path = _RAW_DIR / f"{slug}_{source}.json"
    async with aiofiles.open(path, "w") as f:
        await f.write(json.dumps(data, indent=2))


@retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(3))
async def _fetch_one(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, row: pd.Series, source: str
) -> None:
    async with semaphore:
        dataset_id = config.cb_dataset_id if source == "crunchbase" else config.li_dataset_id
        url = _build_url(row, source)
        data = await scrape_one(client, dataset_id, url)
        await _save_raw(row["name"], source, data)
        _log_status(row["name"], source, "ok")


async def _fetch_one_safe(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, row: pd.Series, source: str
) -> None:
    try:
        await _fetch_one(client, semaphore, row, source)
    except Exception as exc:
        _log_status(row["name"], source, "failed", str(exc))


async def fetch_all(companies_df: pd.DataFrame) -> None:
    semaphore = asyncio.Semaphore(config.fetch_concurrency)
    async with httpx.AsyncClient(timeout=120.0) as client:
        tasks = []
        for _, row in companies_df.iterrows():
            has_cb = has_identifier(row["crunchbase"])
            has_li = has_identifier(row["linkedin"])
            if has_cb:
                tasks.append(_fetch_one_safe(client, semaphore, row, "crunchbase"))
            if has_li:
                tasks.append(_fetch_one_safe(client, semaphore, row, "linkedin"))
            if not has_cb and not has_li:
                _log_status(row["name"], "both", "skipped", "no identifiers")
        await asyncio.gather(*tasks)


async def run_fetch() -> None:
    df = pd.read_sql("SELECT * FROM input_companies", engine)
    await fetch_all(df)
