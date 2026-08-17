"""Ручная отметка «не интересно» — CRM index only (source matches are READ ONLY)."""

from __future__ import annotations

from typing import Tuple

from loguru import logger


def mark_object_not_interesting(
    *,
    tender_db,
    crm_db,
    tender_id: int,
    registry_type: str,
    object_key: str,
    objects_service=None,
) -> Tuple[bool, str]:
    """Hide object in CRM without mutating tender_document_matches on S7."""
    # tender_db kept in signature for callers; source writes are forbidden.
    _ = (tender_db, tender_id, registry_type)

    if crm_db and not getattr(crm_db, "is_offline_mode", lambda: False)():
        try:
            crm_db.execute_update(
                "DELETE FROM crm_objects_index WHERE object_key = %s",
                (object_key,),
            )
        except Exception as exc:
            logger.warning(f"crm_objects_index delete: {exc}")
            return False, f"Ошибка CRM DB: {exc}"
    else:
        return False, "Нет подключения к CRM DB"

    if objects_service is not None:
        objects_service.remove_item_by_key(object_key)

    return True, (
        "Объект убран из CRM индекса "
        "(source tender_document_matches не изменяется — SOURCE_DB_READONLY)"
    )
