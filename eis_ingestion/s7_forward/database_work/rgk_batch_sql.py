"""SQL builders for 44-FZ RGK batch persistence. No DB I/O."""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

from database_work.registry_tables import lookup_order, tables_for_fz

REGISTRY_LOOKUP_COLUMNS = (
    "id",
    "contract_number",
    "final_price",
    "contractor_id",
    "delivery_start_date",
    "delivery_end_date",
    "auction_name",
    "okpd_id",
)

BATCH_UPDATE_COLUMNS = (
    "final_price",
    "contractor_id",
    "delivery_start_date",
    "delivery_end_date",
    "auction_name",
    "okpd_id",
    "initial_price",
    "guarantee_amount",
    "region_id",
)

ALLOWED_TABLES_44 = frozenset(lookup_order(tables_for_fz("44")))
MAIN_TABLE_44 = tables_for_fz("44").main


def _assert_table(table_name: str) -> str:
    if table_name not in ALLOWED_TABLES_44:
        raise ValueError(f"Unexpected registry table: {table_name}")
    return table_name


def build_filename_lookup_sql() -> str:
    return "SELECT file_name FROM file_names_xml WHERE file_name = ANY(%s)"


def build_filename_insert_sql() -> str:
    return "INSERT INTO file_names_xml (file_name) VALUES %s"


def build_okpd_lookup_sql() -> str:
    return "SELECT id, sub_code FROM collection_codes_okpd WHERE sub_code = ANY(%s)"


def build_contractor_lookup_sql() -> str:
    return "SELECT id, inn FROM contractor WHERE inn = ANY(%s)"


def build_registry_lookup_sql(table_name: str) -> str:
    table = _assert_table(table_name)
    cols = ", ".join(REGISTRY_LOOKUP_COLUMNS)
    return f"SELECT {cols} FROM {table} WHERE contract_number = ANY(%s)"


def build_unresolved_lookup_sql() -> str:
    return (
        "SELECT contract_number, reason, payload_json, okpd_codes, contract_subject "
        "FROM rgk_contract_unresolved "
        "WHERE fz_type = %s AND contract_number = ANY(%s)"
    )


def build_unresolved_upsert_sql() -> str:
    return """
INSERT INTO rgk_contract_unresolved (
    fz_type, contract_number, notification_number, reestr_number,
    contract_subject, okpd_codes, okpd_codes_json, raw_file,
    tender_link, reason, payload_json, updated_at
) VALUES %s
ON CONFLICT (fz_type, contract_number) DO UPDATE SET
    notification_number = EXCLUDED.notification_number,
    reestr_number = EXCLUDED.reestr_number,
    contract_subject = COALESCE(EXCLUDED.contract_subject, rgk_contract_unresolved.contract_subject),
    okpd_codes = EXCLUDED.okpd_codes,
    okpd_codes_json = EXCLUDED.okpd_codes_json,
    raw_file = COALESCE(EXCLUDED.raw_file, rgk_contract_unresolved.raw_file),
    tender_link = COALESCE(EXCLUDED.tender_link, rgk_contract_unresolved.tender_link),
    reason = EXCLUDED.reason,
    payload_json = EXCLUDED.payload_json,
    updated_at = NOW()
"""


UPDATE_VALUE_TEMPLATE = (
    "(%s::int, %s::numeric, %s::int, %s::date, %s::date, %s, %s::int, "
    "%s::numeric, %s::numeric, %s::int)"
)


def build_batch_update_sql(table_name: str, columns: Sequence[str] = BATCH_UPDATE_COLUMNS) -> str:
    table = _assert_table(table_name)
    assignments = [f"{col} = COALESCE(v.{col}, t.{col})" for col in columns]
    assignments.append("updated_at = NOW()")
    value_cols = ", ".join(["id"] + list(columns))
    return (
        f"UPDATE {table} AS t SET {', '.join(assignments)} "
        f"FROM (VALUES %s) AS v({value_cols}) "
        "WHERE t.id = v.id"
    )


def build_canonical_insert_sql(columns: Sequence[str]) -> str:
    cols = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    return (
        f"INSERT INTO {MAIN_TABLE_44} ({cols}) VALUES ({placeholders}) RETURNING id, contract_number"
    )


def merge_registry_priority(
    rows_by_table: Mapping[str, Iterable[Sequence]],
    table_order: Optional[Sequence[str]] = None,
) -> dict[str, dict]:
    """First table in lifecycle order wins. rows: lookup column tuples."""
    order = list(table_order or lookup_order(tables_for_fz("44")))
    found: dict[str, dict] = {}
    for table_name in order:
        for row in rows_by_table.get(table_name, ()):
            number = str(row[1]).strip() if row[1] is not None else ""
            if not number or number in found:
                continue
            found[number] = {
                "table_name": table_name,
                "record_id": int(row[0]),
                "contract_number": number,
                "final_price": row[2],
                "contractor_id": row[3],
                "delivery_start_date": row[4],
                "delivery_end_date": row[5],
                "auction_name": row[6],
                "okpd_id": row[7],
            }
    return found


def statements_for_batch(
    *,
    lookup_tables: int,
    update_tables: int,
    promote_sources: int,
    inserts: int,
    unresolved_writes: int,
    contractor_inserts: int,
    has_filenames: bool,
    has_links: bool,
) -> dict[str, int]:
    """Upper bound of SQL statements for one RGK batch (one COMMIT)."""
    selects = 4 + lookup_tables  # filenames, okpd, contractor, unresolved + registry tables
    updates = update_tables
    inserts_n = inserts + contractor_inserts + (1 if has_filenames else 0)
    if unresolved_writes:
        inserts_n += 1
    if has_links:
        inserts_n += 1
    # promote: existence insert + replica + delete + origin per source table
    updates += promote_sources * 2
    inserts_n += promote_sources
    return {
        "selects": selects,
        "updates": updates,
        "inserts": inserts_n,
        "commits": 1,
        "statements": selects + updates + inserts_n + 1,
    }
