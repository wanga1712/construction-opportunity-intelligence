"""Проверка готовности закупки к завершению."""

from __future__ import annotations

from typing import Any, List, Optional, Set

from .resume_constants import (
    BLOCKING_FILE_STATUSES,
    STATUS_COMPLETED,
    STATUS_ERROR_MEMORY,
    STATUS_PENDING_RESUME,
)


def blocking_statuses_for_completion() -> Set[str]:
    return set(BLOCKING_FILE_STATUSES)


def can_complete_tender_files(
    rows: List[tuple],
    *,
    processed_in_run: Optional[Set[str]] = None,
) -> bool:
    """
    rows: (file_name, status) из processed_documents для закупки.
    processed_in_run: имена файлов, обработанных в текущем проходе (допускаем processing).
    """
    in_run = processed_in_run or set()
    for file_name, status in rows:
        if status == STATUS_COMPLETED:
            continue
        if status == STATUS_ERROR_MEMORY:
            continue
        if status in blocking_statuses_for_completion():
            if status == "processing" and file_name in in_run:
                continue
            return False
    return True


def count_by_status(rows: List[tuple], status: str) -> int:
    return sum(1 for _, st in rows if st == status)
