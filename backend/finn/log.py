import logging
import os


def setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("FINN_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    # yfinance logs every empty ticker at ERROR; we report those ourselves.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
