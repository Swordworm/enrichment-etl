from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).parent.parent


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    brightdata_token: str = ""
    cb_dataset_id: str = "gd_l1vijqt9jfj7olije"
    li_dataset_id: str = "gd_l1vikfnt1wgvvqz95w"
    brightdata_base_url: str = "https://api.brightdata.com/datasets/v3"
    poll_interval_s: int = 5
    fetch_concurrency: int = 5
    raw_ttl_hours: int = 24
    db_path: Path = Field(default=_ROOT / "data" / "enrichment.db")
    xlsx_path: Path = Field(default=_ROOT / "data" / "input" / "candidate_take_home.xlsx")


config = Config()
