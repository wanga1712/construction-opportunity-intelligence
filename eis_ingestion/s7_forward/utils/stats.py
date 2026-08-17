"""
Глобальный сборщик статистики вставок в БД и обработанных сущностей.
"""
from threading import Lock
from typing import Dict


class _StatsCollector:
    def __init__(self):
        self._counts: Dict[str, int] = {}
        self._lock = Lock()

    def increment(self, key: str, value: int = 1) -> None:
        if not key:
            return
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + value

    def get_snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


_collector = _StatsCollector()


def increment(key: str, value: int = 1) -> None:
    _collector.increment(key, value)


def get_snapshot() -> Dict[str, int]:
    return _collector.get_snapshot()


def reset() -> None:
    _collector.reset()


