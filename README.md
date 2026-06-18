# enrichment-etl

Company enrichment ETL: fetch 100 companies from Brightdata (Crunchbase + LinkedIn), land raw data into typed SQLite tables, reconcile into a canonical dataset.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Brightdata API token ([Account Settings → API Keys](https://brightdata.com/cp/setting/users))

## Setup

```bash
uv sync
cp .env.example .env
# fill in BRIGHTDATA_TOKEN in .env
```

Place `candidate_take_home.xlsx` in `data/input/` (two sheets: `candidate_take_home`, `database`).

## Run

```bash
uv run python src/main.py
```

Pipeline steps run in sequence:

1. **DB init** — creates `data/enrichment.db`, seeds `input_companies` (100 rows) and `canonical` (1000 rows) from xlsx on first run
2. **Fetch** — calls Brightdata Crunchbase and LinkedIn scrapers for each company concurrently (semaphore=5), saves raw JSON to `data/raw/`
3. **Parse CB** — extracts CB responses into `cb_companies`, `cb_categories`, `cb_locations`, `cb_funding_rounds`
4. **Parse LI** — extracts LI responses into `li_companies`, `li_locations`
5. **Reconcile** — matches each input company to canonical (crunchbase slug → domain → linkedin → pitchbook → fuzzy name), merges enriched fields, inserts new records
6. **Export** — writes `data/output/canonical.csv`

## Outputs

| Path | Description |
|---|---|
| `data/enrichment.db` | SQLite — all 9 landing + canonical tables |
| `data/raw/*.json` | Raw Brightdata API responses (one file per company per source) |
| `data/output/canonical.csv` | Final canonical dataset (~1000 rows + new companies) |

## Schema

All tables defined as SQLAlchemy `Table()` objects in [`src/db.py`](src/db.py).

**Seed tables:** `input_companies`, `canonical`, `enrichment_log`

**Crunchbase landing:** `cb_companies`, `cb_categories`, `cb_locations`, `cb_funding_rounds`

**LinkedIn landing:** `li_companies`, `li_locations`

## Reconcile logic

Match priority (first hit wins):
1. Crunchbase slug exact match
2. Domain exact match (normalized: strip `www.`, lowercase)
3. LinkedIn handle exact match
4. PitchBook URL exact match
5. Company name fuzzy match (threshold 0.85)

Field merge: CB data preferred for dynamic fields (operating status, headcount, description); static fields (address, founded date, contact) fill null only; existing `guru_permalink` never overwritten.

## Notes

- xlsx uses strict OOXML format — `openpyxl` cannot read it; [`python-calamine`](https://github.com/dimastbk/python-calamine) is used instead
- Companies with no CB slug and no LI handle are logged as `skipped` in `enrichment_log`
- SQLAlchemy Core used throughout — swap `sqlite:///...` for `postgresql+psycopg2://...` to run against Cloud SQL

## Cloud orchestration

See [`docs/cloud_orchestration.md`](docs/cloud_orchestration.md) for the GCP architecture: Pub/Sub-based job queue, atomic worker claiming, Redis token-bucket rate limiting, DLQ handling, and observability.
