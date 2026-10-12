#!/usr/bin/env python3
"""Инкрементальная проекция ГИДРОИЗОЛЯЦИОННЫХ контрактов 615-ПП S7 -> CRM (S13).

Задача: 615-ПП не тащится в crm_procurements целиком. Проецируются ТОЛЬКО
записи, которые подтверждает УЖЕ СУЩЕСТВУЮЩИЙ production-критерий
гидроизоляции. Остальные 615 остаются на source-слое S7.

Переиспользуемые (не новые) критерии:
  * S7-загрузчик 615: parsing_xml/xml_parser.py::_detect_waterproofing
    -> персистится в reestr_contract_615_pp.is_waterproofing / .matched_keywords;
  * канонический CRM-матчер товарных групп:
    src/constants/product_groups.detect_product_groups_from_text
    (в частности PRODUCT_GROUP_KEYWORDS["waterproofing"]).

Запись (форма и семантика канонического crm_procurements_sync):
  * UPSERT ON CONFLICT (source_table, source_id);
  * crm_stage='razygranye', award_status='awarded'
    — 615-ПП это уже состоявшиеся контракты/результаты, а не открытый приём
      заявок; такие строки НЕ должны попадать в "Идут торги";
  * никакого DDL/TRUNCATE, crm_created_at не сбрасывается, только инкремент.

Codes (как у refresh_waterproofing_615_link.py):
  0 — успех, 1 — источник торгов S7 недоступен, 2 — CRM БД недоступна.

Использование:
  PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89 \
    .venv313/bin/python scripts/run_615_waterproofing_projection.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/pythonProject89")

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_615_waterproofing_projection")

import psycopg2.extras

from src.constants.product_groups import detect_product_groups_from_text
from src.services.db_bootstrap import connect_databases
from src.services.procurement_identity import canonical_tender_link_for_storage

SOURCE_TABLE = "reestr_contract_615_pp"
S7_615_TABLE = "public.reestr_contract_615_pp"
# 615-ПП — реестр контрактов (капремонт МКД), а не открытая закупка.
CRM_STAGE = "razygranye"
AWARD_STATUS = "awarded"

_S7_SELECT = f"""
    SELECT id, contract_number, auction_name, work_kind_name, is_waterproofing,
           matched_keywords, initial_price, final_price, customer,
           delivery_region, region_id, start_date, end_date,
           delivery_start_date, delivery_end_date, tender_link
    FROM {S7_615_TABLE}
    ORDER BY id
"""

_UPSERT_SQL = """
    INSERT INTO crm_procurements (
        source_table, source_id, contract_number, auction_name,
        initial_price, final_price, customer, delivery_region, region_id,
        start_date, end_date, delivery_start_date, delivery_end_date,
        tender_link, source_updated_at,
        crm_stage, award_status, qualification_state
    ) VALUES (
        %(source_table)s, %(source_id)s, %(contract_number)s, %(auction_name)s,
        %(initial_price)s, %(final_price)s, %(customer)s, %(delivery_region)s, %(region_id)s,
        %(start_date)s, %(end_date)s, %(delivery_start_date)s, %(delivery_end_date)s,
        %(tender_link)s, NULL,
        %(crm_stage)s, %(award_status)s, 'unassessed'
    )
    ON CONFLICT (source_table, source_id) DO UPDATE SET
        auction_name   = EXCLUDED.auction_name,
        initial_price  = EXCLUDED.initial_price,
        end_date       = EXCLUDED.end_date,
        tender_link    = COALESCE(EXCLUDED.tender_link, crm_procurements.tender_link),
        crm_updated_at = now()
    WHERE crm_procurements.crm_stage NOT IN ('manual_hold')
"""


def _s7_615_rows(tender_db: Any) -> list[dict[str, Any]]:
    """READ ONLY: все контракты 615-ПП из источника (S7 tender_monitor)."""
    conn = tender_db.get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_S7_SELECT)
        return [dict(row) for row in cur.fetchall()]


def is_waterproofing_615(row: dict[str, Any]) -> bool:
    """Существующий production-критерий гидроизоляции для 615-ПП.

    Любой из сигналов (оба — результат уже принятых в проекте матчеров):
      1) персистентный флаг/ключи S7-загрузчика 615 (is_waterproofing /
         matched_keywords);
      2) канонический CRM-матчер товарных групп по тексту предмета работ.
    """
    if row.get("is_waterproofing"):
        return True
    if str(row.get("matched_keywords") or "").strip():
        return True
    text = " ".join(
        str(row.get(key) or "") for key in ("auction_name", "work_kind_name")
    )
    return "waterproofing" in detect_product_groups_from_text(text)


def _existing_source_ids(crm_db: Any) -> set[int]:
    rows = crm_db.execute_query(
        "SELECT source_id FROM crm_procurements WHERE source_table = %(st)s",
        {"st": SOURCE_TABLE},
    ) or []
    ids: set[int] = set()
    for row in rows:
        value = row["source_id"] if isinstance(row, dict) else row[0]
        if value is not None:
            ids.add(int(value))
    return ids


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    source_id = int(row["id"])
    contract_number = str(row.get("contract_number") or source_id)
    auction_name = (
        str(row.get("auction_name") or "").strip()
        or str(row.get("work_kind_name") or "").strip()
        or f"615-PP contract {contract_number}"
    )
    return {
        "source_table": SOURCE_TABLE,
        "source_id": source_id,
        "contract_number": contract_number,
        "auction_name": auction_name,
        "initial_price": row.get("initial_price"),
        "final_price": row.get("final_price"),
        "customer": row.get("customer"),
        "delivery_region": row.get("delivery_region"),
        "region_id": row.get("region_id"),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
        "delivery_start_date": row.get("delivery_start_date"),
        "delivery_end_date": row.get("delivery_end_date"),
        "tender_link": canonical_tender_link_for_storage(
            source_table=SOURCE_TABLE,
            contract_number=contract_number,
            tender_link=row.get("tender_link"),
        ),
        "crm_stage": CRM_STAGE,
        "award_status": AWARD_STATUS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Incremental 615-PP waterproofing projection S7 -> CRM"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Посчитать проекцию без записи в CRM",
    )
    args = parser.parse_args(argv)

    _radar_db, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning("connect_databases warnings: %s", warn)
    if tender_db is None:
        logger.error("Источник торгов S7 недоступен — проекция невозможна")
        return 1
    if crm_db is None:
        logger.error("CRM БД недоступна — проекция невозможна")
        return 2

    rows = _s7_615_rows(tender_db)
    matched = [row for row in rows if is_waterproofing_615(row)]
    rejected = len(rows) - len(matched)
    logger.info("615-ПП source rows=%d waterproofing=%d rejected=%d",
                len(rows), len(matched), rejected)

    existing = _existing_source_ids(crm_db)
    projected = already = errors = 0

    for row in matched:
        payload = _payload(row)
        if payload["source_id"] in existing:
            already += 1
        try:
            if args.dry_run:
                projected += 1
                continue
            crm_db.execute_update(_UPSERT_SQL, payload)
            projected += 1
        except Exception as exc:  # noqa: BLE001 — не роняем весь прогон
            logger.warning("upsert 615/%s: %s", payload["source_id"], exc)
            errors += 1

    for row in matched[:5]:
        payload = _payload(row)
        logger.info(
            "trace id=%s contract=%s -> waterproofing=YES -> crm_stage=%s",
            payload["source_id"], payload["contract_number"], CRM_STAGE,
        )

    print(f"615_MATCHED_WATERPROOFING={len(matched)}")
    print(f"615_REJECTED_OTHER_CATEGORIES={rejected}")
    print(f"615_PROJECTED_WATERPROOFING={projected}")
    print(f"615_PROJECTED_ALREADY_PRESENT={already}")
    print("615_PROJECTED_OTHER_CATEGORIES=0")
    print(f"615_PROJECTION_ERRORS={errors}")
    print(f"615_MODE={'DRY_RUN' if args.dry_run else 'APPLY'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())