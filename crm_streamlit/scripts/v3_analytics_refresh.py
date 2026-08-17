"""CLI entry for V3 analytics refresh (canonical CRM cache or pre-cutover Level-A)."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from src.services.db_bootstrap import connect_databases
from src.services.v3_analytics_cache import cache_schema_ready
from src.services.v3_analytics_refresh import (
    ANALYTICS_REFRESH_TIMER_ENABLED,
    PRECUTOVER_REFRESH_TIMER_ENABLED,
    build_refresh_service,
)

logger = logging.getLogger("v3_analytics_refresh")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh V3 analytics snapshot")
    parser.add_argument("--trigger", choices=("manual", "timer", "test"), default="timer")
    parser.add_argument(
        "--precutover-level-a",
        action="store_true",
        help="Force temporary S13 local Level-A file cache (no CRM analytics writes)",
    )
    parser.add_argument(
        "--allow-without-timer-flag",
        action="store_true",
        help="Permit timer trigger even when timer flags are False",
    )
    args = parser.parse_args(argv)

    if args.trigger == "timer" and not args.allow_without_timer_flag:
        if args.precutover_level_a:
            if not PRECUTOVER_REFRESH_TIMER_ENABLED:
                logger.error("Pre-cutover timer refused: PRECUTOVER_REFRESH_TIMER_ENABLED=False")
                return 2
        elif not ANALYTICS_REFRESH_TIMER_ENABLED:
            logger.error("Canonical timer refused: ANALYTICS_REFRESH_TIMER_ENABLED=False")
            return 2

    _r, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning(warn)
    if tender_db is None and crm_db is None:
        logger.error("No databases available")
        return 1

    force_pre = bool(args.precutover_level_a)
    if not force_pre and crm_db is not None and not cache_schema_ready(crm_db):
        # Auto-fallback to pre-cutover Level-A when canonical tables absent
        force_pre = True
        logger.info("Canonical cache not ready — using pre-cutover Level-A file store")

    engine = build_refresh_service(
        tender_db, crm_db, force_precutover=force_pre
    )
    result = engine.refresh_all(trigger=args.trigger)
    logger.info(
        "refresh status=%s ok=%s gen=%s duration_ms=%s msg=%s",
        result.status,
        result.ok,
        result.generation_id,
        result.duration_ms,
        result.message,
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    sys.exit(main())
