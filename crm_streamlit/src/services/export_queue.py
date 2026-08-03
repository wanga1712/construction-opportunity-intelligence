"""Pure operations for a PDF-export INN queue."""
from typing import List, Set

from modules.crm.analytics.inn_normalize import normalize_inn

def queue_size(queue: Set[str]) -> int:
    return len(queue)


def add_to_queue(queue: Set[str], inn: str) -> None:
    canonical = normalize_inn(inn)
    if not canonical:
        return
    queue.add(canonical)


def remove_from_queue(queue: Set[str], inn: str) -> None:
    canonical = normalize_inn(inn)
    if not canonical:
        return
    queue.discard(canonical)


def is_queued(queue: Set[str], inn: str) -> bool:
    canonical = normalize_inn(inn)
    if not canonical:
        return False
    return canonical in queue


def list_queued_inns(queue: Set[str]) -> List[str]:
    return sorted(queue)


def clear_queue(queue: Set[str]) -> None:
    queue.clear()


def migrate_queue_inn(queue: Set[str], old_inn: str, new_inn: str) -> None:
    """Перенести компанию в очереди PDF при смене ИНН."""
    old = normalize_inn(old_inn)
    new = normalize_inn(new_inn)
    if not old or not new or old == new:
        return
    if old in queue:
        queue.discard(old)
        queue.add(new)


def toggle_export_for_inn(queue: Set[str], inn: str) -> None:
    """Переключить компанию в очереди PDF (кнопка 📄)."""
    if is_queued(queue, inn):
        remove_from_queue(queue, inn)
    else:
        add_to_queue(queue, inn)


class ExportQueue:
    """Thin mutable wrapper around the pure queue helpers (set of normalized INNs)."""

    def __init__(self, initial: Set[str] | None = None) -> None:
        self._queue: Set[str] = set(initial or ())

    def __len__(self) -> int:
        return queue_size(self._queue)

    def add(self, inn: str) -> None:
        add_to_queue(self._queue, inn)

    def remove(self, inn: str) -> None:
        remove_from_queue(self._queue, inn)

    def contains(self, inn: str) -> bool:
        return is_queued(self._queue, inn)

    def list_inns(self) -> List[str]:
        return list_queued_inns(self._queue)

    def clear(self) -> None:
        clear_queue(self._queue)

    def migrate_inn(self, old_inn: str, new_inn: str) -> None:
        migrate_queue_inn(self._queue, old_inn, new_inn)

    def toggle(self, inn: str) -> None:
        toggle_export_for_inn(self._queue, inn)

    @property
    def raw(self) -> Set[str]:
        return self._queue
