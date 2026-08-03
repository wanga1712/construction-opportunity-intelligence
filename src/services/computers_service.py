"""Load computer tenders by OKPD2 (26.20*) and manage TZ → supplier cards."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from modules.crm.analytics.tender_row_utils import query_dicts
from modules.crm.repositories.tender_registry_constants import registry_label
from src.constants.computer_okpd import COMPUTER_OKPD_ROOTS, compose_okpd_code, is_computer_okpd
from src.services.object_models import ObjectViewItem
from src.services.tender_registry_query import TENDER_TABLES


@dataclass
class ComputerTenderRow:
    key: str
    tender_id: int
    registry_type: str
    name: str
    contract_number: Optional[str] = None
    region: Optional[str] = None
    okpd_code: Optional[str] = None
    okpd_name: Optional[str] = None
    status: Optional[str] = None
    initial_price: Optional[float] = None
    customer_name: Optional[str] = None
    customer_inn: Optional[str] = None
    contractor_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    delivery_end_date: Optional[str] = None
    doc_count: int = 0
    card: Optional[dict] = None


def _date_str(val) -> Optional[str]:
    if not val:
        return None
    return str(val)[:10]


def load_computer_tenders(
    tender_db,
    *,
    limit: int = 200,
    only_open: bool = True,
    region_query: str = "",
) -> List[ComputerTenderRow]:
    """Select registry rows whose OKPD is under 26.20* (computers).

    only_open=True (default): skip *_awarded / *_completed — only tenders that
    have not finished yet. When EIS lag means few open rows, the list may be empty.
    """
    if not tender_db:
        return []

    rows_out: List[ComputerTenderRow] = []
    seen: set[str] = set()

    # Prefer truly open main tables first, then unclear/commission, never awarded if only_open.
    open_first = [
        t for t in TENDER_TABLES
        if "awarded" not in t and "completed" not in t and "bad" not in t
    ]
    awarded = [t for t in TENDER_TABLES if "awarded" in t or "completed" in t]
    tables = open_first if only_open else (open_first + awarded)
    per_table = max(30, limit // max(1, len(tables)))

    for table in tables:
        try:
            chunk = _fetch_table(tender_db, table, limit=per_table, region_query=region_query)
        except Exception as exc:
            logger.warning(f"computers OKPD load skip {table}: {exc}")
            continue
        for row in chunk:
            if row.key in seen:
                continue
            seen.add(row.key)
            rows_out.append(row)
            if len(rows_out) >= limit:
                return rows_out
    return rows_out


def _fetch_table(
    tender_db,
    table: str,
    *,
    limit: int,
    region_query: str,
) -> List[ComputerTenderRow]:
    # Prefer sub_code which often holds the full hierarchical code.
    params: list = []
    okpd_sql = (
        "("
        "okpd.sub_code LIKE %s OR okpd.sub_code LIKE %s OR "
        "CONCAT(okpd.main_code, '.', okpd.sub_code) LIKE %s OR "
        "okpd.main_code LIKE %s"
        ")"
    )
    params.extend(["26.20%", "26.2.%", "26.20%", "26.2%"])

    region_sql = "TRUE"
    if region_query.strip():
        region_sql = "(r.delivery_region ILIKE %s OR reg.name ILIKE %s OR r.auction_name ILIKE %s)"
        q = f"%{region_query.strip()}%"
        params.extend([q, q, q])

    params.append(limit)

    awarded = "awarded" in table or "completed" in table
    contractor_join = (
        "LEFT JOIN contractor con ON con.id = r.contractor_id"
        if awarded
        else "LEFT JOIN contractor con ON FALSE"
    )
    contractor_cols = (
        "COALESCE(NULLIF(con.short_name, ''), con.full_name) AS contractor_name"
        if awarded
        else "NULL::text AS contractor_name"
    )

    sql = f"""
        SELECT
            r.id AS tender_id,
            r.auction_name,
            r.contract_number,
            r.initial_price,
            r.start_date, r.end_date, r.delivery_end_date,
            r.delivery_region,
            reg.name AS region_name,
            okpd.main_code AS okpd_main,
            okpd.sub_code AS okpd_sub,
            okpd.name AS okpd_name,
            COALESCE(NULLIF(c.customer_short_name, ''), c.customer_full_name) AS organizer_name,
            c.customer_inn AS organizer_inn,
            {contractor_cols},
            (
                SELECT COUNT(*) FROM links_documentation_44_fz ld
                WHERE ld.contract_id = r.id
            ) AS doc_count_44,
            (
                SELECT COUNT(*) FROM links_documentation_223_fz ld
                WHERE ld.contract_id = r.id
            ) AS doc_count_223
        FROM {table} r
        LEFT JOIN collection_codes_okpd okpd ON okpd.id = r.okpd_id
        LEFT JOIN customer c ON c.id = r.customer_id
        LEFT JOIN region reg ON reg.id = r.region_id
        {contractor_join}
        WHERE okpd.id IS NOT NULL
          AND {okpd_sql}
          AND {region_sql}
        ORDER BY COALESCE(r.start_date, r.delivery_end_date) DESC NULLS LAST
        LIMIT %s
    """
    # links tables may not exist for all — wrap safer
    try:
        raw = query_dicts(tender_db, sql, tuple(params))
    except Exception:
        # Fallback without doc counts
        sql_fallback = f"""
            SELECT
                r.id AS tender_id,
                r.auction_name,
                r.contract_number,
                r.initial_price,
                r.start_date, r.end_date, r.delivery_end_date,
                r.delivery_region,
                reg.name AS region_name,
                okpd.main_code AS okpd_main,
                okpd.sub_code AS okpd_sub,
                okpd.name AS okpd_name,
                COALESCE(NULLIF(c.customer_short_name, ''), c.customer_full_name) AS organizer_name,
                c.customer_inn AS organizer_inn,
                {contractor_cols},
                0 AS doc_count_44,
                0 AS doc_count_223
            FROM {table} r
            LEFT JOIN collection_codes_okpd okpd ON okpd.id = r.okpd_id
            LEFT JOIN customer c ON c.id = r.customer_id
            LEFT JOIN region reg ON reg.id = r.region_id
            {contractor_join}
            WHERE okpd.id IS NOT NULL
              AND {okpd_sql}
              AND {region_sql}
            ORDER BY COALESCE(r.start_date, r.delivery_end_date) DESC NULLS LAST
            LIMIT %s
        """
        raw = query_dicts(tender_db, sql_fallback, tuple(params))

    out: List[ComputerTenderRow] = []
    for r in raw:
        code = compose_okpd_code(r.get("okpd_main"), r.get("okpd_sub"))
        if not is_computer_okpd(code, name=r.get("okpd_name")):
            continue
        docs = int(r.get("doc_count_44") or 0) + int(r.get("doc_count_223") or 0)
        out.append(
            ComputerTenderRow(
                key=f"tender:{table}:{r['tender_id']}",
                tender_id=int(r["tender_id"]),
                registry_type=table,
                name=r.get("auction_name") or "—",
                contract_number=(r.get("contract_number") or "").strip() or None,
                region=r.get("region_name") or r.get("delivery_region"),
                okpd_code=code,
                okpd_name=r.get("okpd_name"),
                status=registry_label(table),
                initial_price=float(r["initial_price"]) if r.get("initial_price") is not None else None,
                customer_name=r.get("organizer_name"),
                customer_inn=r.get("organizer_inn"),
                contractor_name=r.get("contractor_name"),
                start_date=_date_str(r.get("start_date")),
                end_date=_date_str(r.get("end_date")),
                delivery_end_date=_date_str(r.get("delivery_end_date")),
                doc_count=docs,
            )
        )
    return out


def to_view_item(row: ComputerTenderRow) -> ObjectViewItem:
    return ObjectViewItem(
        key=row.key,
        name=row.name,
        address=row.region,
        segment="other",
        status=row.status,
        sources=["44fz" if "44_fz" in row.registry_type else "223fz"],
        contract_number=row.contract_number,
        region=row.region,
        registry_type=row.registry_type,
        tender_id=row.tender_id,
        customer_name=row.customer_name,
        customer_inn=row.customer_inn,
        contractor_name=row.contractor_name,
        start_date=row.start_date,
        end_date=row.end_date,
        delivery_end_date=row.delivery_end_date,
        quality_tier="basic",
        search_text=" ".join(filter(None, [row.name, row.okpd_code, row.okpd_name, row.contract_number])),
    )


# --- CRM store for supplier-ready cards ---

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS crm_computer_tz_cards (
    object_key TEXT PRIMARY KEY,
    tender_id INTEGER,
    registry_type TEXT,
    contract_number TEXT,
    okpd_code TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    tz_file_names JSONB,
    tz_text_excerpt TEXT,
    supplier_card JSONB,
    model_name TEXT,
    model_version TEXT,
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm_computer_tz_items (
    id BIGSERIAL PRIMARY KEY,
    object_key TEXT NOT NULL,
    tender_id INTEGER,
    registry_type TEXT,
    category TEXT NOT NULL,
    item_name TEXT,
    qty NUMERIC,
    unit TEXT,
    specs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL DEFAULT 'ai',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_crm_computer_tz_items_object_key
    ON crm_computer_tz_items(object_key);
CREATE INDEX IF NOT EXISTS ix_crm_computer_tz_items_category
    ON crm_computer_tz_items(category);
"""


def ensure_computer_cards_schema(crm_db) -> None:
    if not crm_db:
        return
    crm_db.execute_update(_SCHEMA_SQL)


def load_computer_cards(crm_db, keys: Sequence[str]) -> Dict[str, dict]:
    if not crm_db or not keys:
        return {}
    ensure_computer_cards_schema(crm_db)
    placeholders = ",".join(["%s"] * len(keys))
    rows = crm_db.execute_query(
        f"SELECT * FROM crm_computer_tz_cards WHERE object_key IN ({placeholders})",
        tuple(keys),
    ) or []
    return {str(r["object_key"]): dict(r) for r in rows if r.get("object_key")}


def load_computer_items(crm_db, keys: Sequence[str]) -> Dict[str, List[dict]]:
    if not crm_db or not keys:
        return {}
    ensure_computer_cards_schema(crm_db)
    placeholders = ",".join(["%s"] * len(keys))
    rows = crm_db.execute_query(
        f"""
        SELECT object_key, category, item_name, qty, unit, specs
        FROM crm_computer_tz_items
        WHERE object_key IN ({placeholders})
        ORDER BY category, id
        """,
        tuple(keys),
    ) or []
    result: Dict[str, List[dict]] = {}
    for row in rows:
        key = str(row.get("object_key") or "")
        if not key:
            continue
        result.setdefault(key, []).append(
            {
                "category": row.get("category"),
                "name": row.get("item_name"),
                "qty": row.get("qty"),
                "unit": row.get("unit"),
                "specs": row.get("specs") or [],
            }
        )
    return result


def save_computer_card(crm_db, *, object_key: str, payload: dict) -> None:
    if not crm_db:
        return
    ensure_computer_cards_schema(crm_db)
    crm_db.execute_update(
        """
        INSERT INTO crm_computer_tz_cards (
            object_key, tender_id, registry_type, contract_number, okpd_code,
            status, tz_file_names, tz_text_excerpt, supplier_card,
            model_name, model_version, error_message, updated_at
        ) VALUES (
            %(object_key)s, %(tender_id)s, %(registry_type)s, %(contract_number)s, %(okpd_code)s,
            %(status)s, %(tz_file_names)s::jsonb, %(tz_text_excerpt)s, %(supplier_card)s::jsonb,
            %(model_name)s, %(model_version)s, %(error_message)s, NOW()
        )
        ON CONFLICT (object_key) DO UPDATE SET
            status = EXCLUDED.status,
            tz_file_names = EXCLUDED.tz_file_names,
            tz_text_excerpt = EXCLUDED.tz_text_excerpt,
            supplier_card = EXCLUDED.supplier_card,
            model_name = EXCLUDED.model_name,
            model_version = EXCLUDED.model_version,
            error_message = EXCLUDED.error_message,
            updated_at = NOW()
        """,
        {
            "object_key": object_key,
            "tender_id": payload.get("tender_id"),
            "registry_type": payload.get("registry_type"),
            "contract_number": payload.get("contract_number"),
            "okpd_code": payload.get("okpd_code"),
            "status": payload.get("status") or "pending",
            "tz_file_names": json.dumps(payload.get("tz_file_names") or [], ensure_ascii=False),
            "tz_text_excerpt": payload.get("tz_text_excerpt"),
            "supplier_card": json.dumps(payload.get("supplier_card") or {}, ensure_ascii=False),
            "model_name": payload.get("model_name"),
            "model_version": payload.get("model_version"),
            "error_message": payload.get("error_message"),
        },
    )


def replace_computer_items(
    crm_db,
    *,
    object_key: str,
    tender_id: Optional[int],
    registry_type: Optional[str],
    items: Sequence[dict],
) -> None:
    if not crm_db:
        return
    ensure_computer_cards_schema(crm_db)
    crm_db.execute_update(
        "DELETE FROM crm_computer_tz_items WHERE object_key = %s",
        (object_key,),
    )
    for raw in items or []:
        category = str(raw.get("category") or "other").strip().lower() or "other"
        name = str(raw.get("name") or "").strip() or None
        unit = str(raw.get("unit") or "шт").strip() or "шт"
        try:
            qty = float(raw.get("qty")) if raw.get("qty") is not None else None
        except Exception:
            qty = None
        specs = raw.get("specs") if isinstance(raw.get("specs"), list) else []
        crm_db.execute_update(
            """
            INSERT INTO crm_computer_tz_items (
                object_key, tender_id, registry_type, category,
                item_name, qty, unit, specs, source, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'ai', NOW())
            """,
            (
                object_key,
                tender_id,
                registry_type,
                category,
                name,
                qty,
                unit,
                json.dumps(specs, ensure_ascii=False),
            ),
        )


def computer_okpd_caption() -> str:
    roots = ", ".join(COMPUTER_OKPD_ROOTS)
    return f"Отбор только по ОКПД-2: {roots}* (не по названию и не по AI-сегменту здания)."
