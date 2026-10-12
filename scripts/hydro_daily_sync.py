#!/usr/bin/env python3
"""Ежедневная загрузка канонического среза Hydro (паркинги + УК) в CRM.

Запускается systemd timer'ом `crm-hydro-daily-sync.timer`.

Production path:
  S7 nspd_parking (READ ONLY)            — объекты-паркинги и управляющие компании
    → канонический upsert по source_object_id / кадастру / ИНН УК
    → CRM БД (parking_prefunnel_objects, management_companies, crm_hydro_*)

Ручные правки менеджеров не затираются: они лежат в `manual_overrides`, и
загрузчик их не читает и не пишет (миграция `hydro_manual_override_1.sql`).

DDL здесь не применяется: схему создают миграции `src/migrations/hydro_*.sql`.

Коды возврата: 0 — успех (или dry-run), 1 — источник NSPD недоступен,
2 — CRM БД недоступна / схема не готова, 3 — загрузка упала (запись FAILED).

Использование:
  PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89 \\
    .venv313/bin/python scripts/hydro_daily_sync.py
  ... --dry-run        # прочитать источник и посчитать без записи в CRM
  ... --limit 200      # ограничить выборку для отладки
"""
from __future__ import annotations

import argparse
import json
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
logger = logging.getLogger("hydro_daily_sync")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily canonical Hydro sync into CRM DB")
    parser.add_argument("--dry-run", action="store_true", help="Читать источник без записи в CRM")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число объектов")
    args = parser.parse_args(argv)

    from src.services.db_bootstrap import connect_databases
    from src.services.hydro_daily_sync import HydroSyncUnavailable, ensure_tables, run_daily_sync
    from src.services.waterproofing_615 import TenderSourceUnavailable

    _radar_db, _tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning("connect_databases warnings: %s", warn)
    if crm_db is None:
        logger.error("CRM БД недоступна — загрузка невозможна")
        return 2

    try:
        if not args.dry_run:
            ensure_tables(crm_db)
    except Exception as error:  # noqa: BLE001
        logger.error("Схема Hydro не готова: %s", error)
        return 2

    try:
        from src.services.parking_db import ParkingDatabase

        source_db = ParkingDatabase()
        if not source_db.connect():
            logger.error("Источник NSPD недоступен: %s", getattr(source_db, "last_error", "нет связи"))
            return 1
        try:
            report = run_daily_sync(
                source_db=source_db, crm_db=crm_db,
                dry_run=bool(args.dry_run), limit=args.limit,
            )
        finally:
            source_db.close()
    except TenderSourceUnavailable as error:
        logger.error("Источник недоступен: %s", error)
        return 1
    except HydroSyncUnavailable as error:
        logger.error("Hydro недоступен: %s", error)
        return 2
    except Exception as error:  # noqa: BLE001 — статус FAILED уже записан
        logger.exception("Загрузка Hydro упала: %s", error)
        return 3

    logger.info("Hydro daily sync: %s", json.dumps(report, ensure_ascii=False, sort_keys=True))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())