"""Проверка готовности закупки к завершению."""

from __future__ import annotations

from .completion_guard import evaluate_completion_guard


def can_complete_tender_files(
    rows: list[tuple],
    *,
    processed_in_run: set[str] | None = None,
) -> bool:
    """
    rows: (file_name, status) из processed_documents для закупки.
    processed_in_run: имена файлов, обработанных в текущем проходе (допускаем processing).
    """
    del processed_in_run  # processing is never successful under the fail-closed policy
    return evaluate_completion_guard(rows).allowed


def count_by_status(rows: list[tuple], status: str) -> int:
    return sum(1 for _, st in rows if st == status)
