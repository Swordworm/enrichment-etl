import asyncio
from typing import Any

import httpx

from src.config import config


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.brightdata_token}",
        "Content-Type": "application/json",
    }


def _scrape_url(dataset_id: str) -> str:
    return f"{config.brightdata_base_url}/scrape?dataset_id={dataset_id}&include_errors=true"


def _trigger_url(dataset_id: str) -> str:
    return f"{config.brightdata_base_url}/trigger?dataset_id={dataset_id}&include_errors=true"


async def scrape_one(
    client: httpx.AsyncClient, dataset_id: str, url: str
) -> list[dict[str, Any]]:
    """POST a single URL to the sync scrape endpoint. Falls back to async if needed."""
    resp = await client.post(
        _scrape_url(dataset_id),
        json={"input": [{"url": url}]},
        headers=_headers(),
    )
    resp.raise_for_status()
    data = resp.json()
    # sync endpoint returns {"snapshot_id": ...} when processing exceeds ~1 min
    if isinstance(data, dict) and "snapshot_id" in data:
        return await poll_and_download(client, data["snapshot_id"])
    return data


async def poll_and_download(
    client: httpx.AsyncClient, snapshot_id: str
) -> list[dict[str, Any]]:
    progress_url = f"{config.brightdata_base_url}/progress/{snapshot_id}"
    snapshot_url = f"{config.brightdata_base_url}/snapshot/{snapshot_id}?format=json"

    while True:
        resp = await client.get(progress_url, headers=_headers())
        resp.raise_for_status()
        status = resp.json().get("status")
        if status == "ready":
            break
        if status == "failed":
            raise RuntimeError(f"snapshot {snapshot_id} failed")
        await asyncio.sleep(config.poll_interval_s)

    resp = await client.get(snapshot_url, headers=_headers())
    resp.raise_for_status()
    return resp.json()
