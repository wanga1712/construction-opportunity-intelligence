"""Shared, safe queries over tender registry tables."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from modules.crm.analytics.tender_contractors_repository import TenderContractorsRepository
from modules.crm.analytics.tender_row_utils import query_dicts


TENDER_TABLES: Sequence[str] = (
    "reestr_contract_44_fz",
    "reestr_contract_44_fz_commission_work",
    "reestr_contract_44_fz_unclear",
    "reestr_contract_44_fz_unknown",
    "reestr_contract_44_fz_bad",
    "reestr_contract_44_fz_awarded",
    "reestr_contract_44_fz_completed",
    "reestr_contract_223_fz",
    "reestr_contract_223_fz_commission_work",
    "reestr_contract_223_fz_unclear",
    "reestr_contract_223_fz_awarded",
    "reestr_contract_223_fz_completed",
    "reestr_contract_615_pp",
    "reestr_contract_615_pp_commission_work",
)


def _validate_table(table: str) -> str:
    if table not in TENDER_TABLES:
        raise ValueError(f"Unsupported tender registry table: {table!r}")
    return table


def _contractor_sql(table: str) -> tuple[str, str]:
    if "awarded" in table or "completed" in table:
        return (
            "LEFT JOIN contractor con ON con.id = r.contractor_id",
            "COALESCE(NULLIF(con.short_name, ''), con.full_name) AS contractor_name, "
            "con.inn AS contractor_inn",
        )
    return "LEFT JOIN contractor con ON FALSE", "NULL::text AS contractor_name, NULL::text AS contractor_inn"


def fetch_registry_rows_by_ids(
    tender_db,
    registry_type: str,
    ids: Iterable[int],
    *,
    settings=None,
    mode: str = "index",
) -> List[dict]:
    """Fetch registry rows by ids with columns for object cards or details."""
    table = _validate_table(registry_type)
    tender_ids = list(dict.fromkeys(i for i in ids if i is not None))
    if not tender_ids:
        return []
    if mode not in {"index", "detail"}:
        raise ValueError(f"Unsupported registry query mode: {mode!r}")

    filters: list[str] = []
    params: list = []
    if settings:
        region_sql = TenderContractorsRepository(tender_db)._region_filter_sql(settings, params)
        if region_sql and region_sql != "TRUE":
            filters.append(region_sql)
    where_extra = " AND ".join(f"({clause})" for clause in filters) or "TRUE"
    contractor_join, contractor_cols = _contractor_sql(table)
    detail_cols = """
        r.tender_link, r.initial_price, r.final_price,
        okpd.main_code AS okpd_main, okpd.sub_code AS okpd_sub, okpd.name AS okpd_name,
        tp.trading_platform_name AS platform_name, tp.trading_platform_url AS platform_url,
    """ if mode == "detail" else ""
    placeholders = ",".join(["%s"] * len(tender_ids))
    return query_dicts(
        tender_db,
        f"""
        SELECT
            r.id AS tender_id, r.auction_name, r.contract_number,
            {detail_cols}
            r.delivery_address, r.delivery_region, r.region_id, r.customer AS balance_holder,
            r.start_date, r.end_date, r.delivery_start_date, r.delivery_end_date,
            reg.name AS region_name,
            COALESCE(NULLIF(c.customer_short_name, ''), c.customer_full_name) AS organizer_name,
            c.customer_inn AS organizer_inn, {contractor_cols}
        FROM {table} r
        LEFT JOIN customer c ON c.id = r.customer_id
        LEFT JOIN region reg ON reg.id = r.region_id
        LEFT JOIN collection_codes_okpd okpd ON okpd.id = r.okpd_id
        LEFT JOIN trading_platform tp ON tp.id = r.trading_platform_id
        {contractor_join}
        WHERE r.id IN ({placeholders}) AND {where_extra}
        """,
        tuple(params + tender_ids),
    )


def fetch_registry_rows_by_numbers(
    tender_db,
    tables: Iterable[str],
    numbers: Iterable[str],
) -> Dict[str, dict]:
    """Return the highest-priority current row for each contract number."""
    requested = list(dict.fromkeys(n.strip() for n in numbers if n and n.strip()))
    if not requested:
        return {}
    result: Dict[str, dict] = {}
    placeholders = ",".join(["%s"] * len(requested))
    for table in tables:
        _validate_table(table)
        contractor_join, contractor_cols = _contractor_sql(table)
        try:
            rows = query_dicts(
                tender_db,
                f"""
            SELECT
                %s::text AS current_table, r.id AS current_tender_id,
                r.contract_number, r.auction_name, r.start_date, r.end_date,
                r.delivery_start_date, r.delivery_end_date, r.initial_price, r.final_price,
                r.customer AS balance_holder,
                COALESCE(NULLIF(c.customer_short_name, ''), c.customer_full_name) AS organizer_name,
                c.customer_inn AS organizer_inn, {contractor_cols}
            FROM {table} r
            LEFT JOIN customer c ON c.id = r.customer_id
            {contractor_join}
            WHERE r.contract_number IN ({placeholders})
            """,
                (table, *requested),
            )
        except Exception:
            continue
        for row in rows:
            number = (row.get("contract_number") or "").strip()
            if number and (
                number not in result
                or table_priority(table) > table_priority(result[number]["current_table"])
            ):
                result[number] = dict(row)
    return result


def table_priority(table: Optional[str]) -> int:
    if not table:
        return 0
    if table.endswith(("_44_fz", "_223_fz", "_615_pp")):
        return 40
    if table.endswith("_commission_work"):
        return 35
    if table.endswith(("_unclear", "_unknown")):
        return 34
    if table.endswith("_awarded"):
        return 25
    if table.endswith("_completed"):
        return 20
    if table.endswith("_bad"):
        return 10
    return 0
