import asyncio
import logging

from src.db import init_db
from src.fetch import run_fetch
from src.parse_crunchbase import parse_all as parse_cb
from src.parse_linkedin import parse_all as parse_li
from src.reconcile import reconcile_all
from src.utils import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()

    logger.info("Initializing DB...")
    init_db()

    logger.info("Fetching enrichment data from Brightdata...")
    asyncio.run(run_fetch())

    logger.info("Parsing Crunchbase responses...")
    parse_cb()

    logger.info("Parsing LinkedIn responses...")
    parse_li()

    logger.info("Reconciling to canonical...")
    reconcile_all()

    logger.info("Done.")


if __name__ == "__main__":
    main()
