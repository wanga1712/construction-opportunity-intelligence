#!/usr/bin/env python3
"""Ежедневное обновление связки 615-ПП ↔ УК для доски гидроизоляции.

Запускается systemd timer'ом `crm-waterproofing-615-link.timer`.

Production path:
  S7 tender_monitor (READ ONLY, strict)  — контракты капремонта 615-ПП
  S7 nspd_parking (READ ONLY)            — портфель домов УК
    → сопоставление «улица + дом»
    → CRM БД (crm_waterproofing_615_*)

DDL здесь не применяется: схему создаёт миграция
`src/migrations/waterproofing_615_uk_link_store_1.sql`. Если таблиц нет,
скрипт завершается с кодом 3 и ничего не пишет.

Коды возврата: 0 — успех, 1 — источник торгов недоступен (права/связь),
2 — хранилище CRM недоступно, 3 — схема хранилища не создана.

Использование:
  PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89 \\
    .venv313/bin/python scripts/refresh_waterproofing_615_link.py
  ... --dry-run   # посчитать связку без записи в CRM
"""
from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/pythonProject89")

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=False)
load_dotenv(override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("refresh_waterproofing_615_link")

from src.services.db_bootstrap import connect_databases
from src.services.waterproofing_615 import TenderSourceUnavailable
from src.services.waterproofing_615_refresh import run_refresh
from src.services.waterproofing_615_store import StoreNotReady, StoreUnavailable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh 615-PP UK linkage in CRM DB")
    parser.add_argument("--dry-run", action="store_true", help="Считать связку без записи в CRM")
    args = parser.parse_args(argv)

    _radar_db, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning("connect_databases warnings: %s", warn)
    if tender_db is None:
        logger.error("Источник торгов недоступен — обновление невозможно")
        return 1
    if crm_db is None:
        logger.error("CRM БД недоступна — обновление невозможно")
        return 2

    try:
        report = run_refresh(
            tender_db=tender_db, crm_db=crm_db, dry_run=bool(args.dry_run)
        )
    except StoreNotReady as error:
        logger.error("Схема хранилища 615-ПП не создана: %s", error)
        return 3
    except StoreUnavailable as error:
        logger.error("Хранилище 615-ПП недоступно: %s", error)
        return 2
    except TenderSourceUnavailable as error:
        logger.error("Источник торгов 615-ПП недоступен: %s", error)
        return 1

    logger.info("615-PP linkage refresh: %s", report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
