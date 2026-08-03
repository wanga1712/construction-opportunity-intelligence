"""Soft reclassify queue rows between open/awarded contours."""
from __future__ import annotations


RECLASSIFY_SQL = [
    (
        "44_open_to_awarded",
        """
        UPDATE document_processing_queue q
        SET table_source = 'reestr_contract_44_fz_awarded',
            error_message = CONCAT('soft_reclassify:', COALESCE(error_message, ''))
        WHERE q.status = 'pending'
          AND q.table_source = 'reestr_contract_44_fz'
          AND EXISTS (
            SELECT 1
            FROM reestr_contract_44_fz_awarded a
            WHERE a.contract_number = q.contract_reg_number
          )
        """,
    ),
    (
        "223_open_to_awarded",
        """
        UPDATE document_processing_queue q
        SET table_source = 'reestr_contract_223_fz_awarded',
            error_message = CONCAT('soft_reclassify:', COALESCE(error_message, ''))
        WHERE q.status = 'pending'
          AND q.table_source = 'reestr_contract_223_fz'
          AND EXISTS (
            SELECT 1
            FROM reestr_contract_223_fz_awarded a
            WHERE a.contract_number = q.contract_reg_number
          )
        """,
    ),
    (
        "44_awarded_to_open",
        """
        UPDATE document_processing_queue q
        SET table_source = 'reestr_contract_44_fz',
            error_message = CONCAT('soft_reclassify:', COALESCE(error_message, ''))
        WHERE q.status = 'pending'
          AND q.table_source = 'reestr_contract_44_fz_awarded'
          AND EXISTS (
            SELECT 1
            FROM reestr_contract_44_fz o
            WHERE o.contract_number = q.contract_reg_number
          )
        """,
    ),
    (
        "223_awarded_to_open",
        """
        UPDATE document_processing_queue q
        SET table_source = 'reestr_contract_223_fz',
            error_message = CONCAT('soft_reclassify:', COALESCE(error_message, ''))
        WHERE q.status = 'pending'
          AND q.table_source = 'reestr_contract_223_fz_awarded'
          AND EXISTS (
            SELECT 1
            FROM reestr_contract_223_fz o
            WHERE o.contract_number = q.contract_reg_number
          )
        """,
    ),
]


def soft_reclassify_docs_queue(tender_db) -> dict:
    if not tender_db:
        return {"error": "Tender DB недоступна"}
    stats = {"total": 0}
    for name, sql in RECLASSIFY_SQL:
        updated = tender_db.execute_update(sql) or 0
        try:
            updated_n = int(updated)
        except Exception:
            updated_n = 0
        stats[name] = updated_n
        stats["total"] += updated_n
    return stats

