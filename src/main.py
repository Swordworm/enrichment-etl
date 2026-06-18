import asyncio

from src.db import init_db
from src.fetch import run_fetch
from src.parse_crunchbase import parse_all as parse_cb
from src.parse_linkedin import parse_all as parse_li
from src.reconcile import reconcile_all


def main() -> None:
    print("Initializing DB...")
    init_db()

    print("Fetching enrichment data from Brightdata...")
    asyncio.run(run_fetch())

    print("Parsing Crunchbase responses...")
    parse_cb()

    print("Parsing LinkedIn responses...")
    parse_li()

    print("Reconciling to canonical...")
    reconcile_all()

    print("Done.")


if __name__ == "__main__":
    main()
