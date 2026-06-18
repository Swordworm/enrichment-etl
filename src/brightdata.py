import asyncio
from typing import Any

import httpx


class BrightdataClient:
    def __init__(
        self,
        dataset_id: str,
        token: str,
        base_url: str,
        poll_interval_s: int,
    ) -> None:
        self.dataset_id = dataset_id
        self._token = token
        self._base_url = base_url
        self._poll_interval_s = poll_interval_s
        self._client = httpx.AsyncClient(timeout=120.0)

    @classmethod
    def crunchbase(cls, cfg: Any) -> "BrightdataClient":
        return cls(cfg.cb_dataset_id, cfg.brightdata_token, cfg.brightdata_base_url, cfg.poll_interval_s)

    @classmethod
    def linkedin(cls, cfg: Any) -> "BrightdataClient":
        return cls(cfg.li_dataset_id, cfg.brightdata_token, cfg.brightdata_base_url, cfg.poll_interval_s)

    async def __aenter__(self) -> "BrightdataClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.__aexit__(*args)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _scrape_url(self) -> str:
        return f"{self._base_url}/scrape?dataset_id={self.dataset_id}&include_errors=true"

    async def scrape(self, url: str) -> list[dict[str, Any]]:
        resp = await self._client.post(
            self._scrape_url(),
            json={"input": [{"url": url}]},
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "snapshot_id" in data:
            return await self._poll_and_download(data["snapshot_id"])
        return data

    async def _poll_and_download(self, snapshot_id: str) -> list[dict[str, Any]]:
        progress_url = f"{self._base_url}/progress/{snapshot_id}"
        snapshot_url = f"{self._base_url}/snapshot/{snapshot_id}?format=json"

        while True:
            resp = await self._client.get(progress_url, headers=self._headers())
            resp.raise_for_status()
            status = resp.json().get("status")
            if status == "ready":
                break
            if status == "failed":
                raise RuntimeError(f"snapshot {snapshot_id} failed")
            await asyncio.sleep(self._poll_interval_s)

        resp = await self._client.get(snapshot_url, headers=self._headers())
        resp.raise_for_status()
        return resp.json()
