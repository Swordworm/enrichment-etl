import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import pandas as pd
from slugify import slugify
from sqlalchemy import insert
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm.asyncio import tqdm

from src.brightdata import BrightdataClient
from src.config import config
from src.db import engine, enrichment_log

_RAW_DIR = Path(__file__).parent.parent / "data" / "raw"


def has_identifier(val) -> bool:
    # xlsx empty cells = NaN; defensive check also handles literal "null" strings
    return pd.notna(val) and str(val).strip().lower() != "null"


def _source_name(client: BrightdataClient) -> str:
    return "crunchbase" if client.dataset_id == config.cb_dataset_id else "linkedin"


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


def _is_cached(company_name: str, source: str) -> bool:
    path = _RAW_DIR / f"{slugify(company_name)}_{source}.json"
    if not path.exists():
        return False
    age_hours = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600
    return age_hours < config.raw_ttl_hours


@retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(3))
async def _fetch_one(
    client: BrightdataClient, semaphore: asyncio.Semaphore, row: pd.Series
) -> None:
    source = _source_name(client)
    async with semaphore:
        url = _build_url(row, source)
        data = await client.scrape(url)
        await _save_raw(row["name"], source, data)
        _log_status(row["name"], source, "ok")


async def _fetch_one_safe(
    client: BrightdataClient, semaphore: asyncio.Semaphore, row: pd.Series
) -> None:
    source = _source_name(client)
    if _is_cached(row["name"], source):
        return
    try:
        await _fetch_one(client, semaphore, row)
    except Exception as exc:
        _log_status(row["name"], source, "failed", str(exc))


async def fetch_all(companies_df: pd.DataFrame) -> None:
    semaphore = asyncio.Semaphore(config.fetch_concurrency)
    async with (
        BrightdataClient.crunchbase(config) as cb,
        BrightdataClient.linkedin(config) as li,
    ):
        tasks = []
        for _, row in companies_df.iterrows():
            has_cb = has_identifier(row["crunchbase"])
            has_li = has_identifier(row["linkedin"])
            if has_cb:
                tasks.append(_fetch_one_safe(cb, semaphore, row))
            if has_li:
                tasks.append(_fetch_one_safe(li, semaphore, row))
            if not has_cb and not has_li:
                _log_status(row["name"], "both", "skipped", "no identifiers")
        await tqdm.gather(*tasks, desc="Fetching")


async def run_fetch() -> None:
    df = pd.read_sql("SELECT * FROM input_companies", engine)
    await fetch_all(df)
