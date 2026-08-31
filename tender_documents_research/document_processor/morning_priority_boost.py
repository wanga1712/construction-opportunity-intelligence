"""Ежедневный утренний буст приоритета новых контрактов."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from typing import Optional

from utils.logger_config import get_logger


class MorningPriorityBoost:
    """
    Раз в сутки после MORNING_PRIORITY_HOUR (по умолчанию 11:00)
    сигнализирует, что нужно принудительно подтянуть новые реестры,
    даже если очередь забита разыгранными закупками.
    """

    def __init__(self, hour: Optional[int] = None) -> None:
        self.logger = get_logger()
        env_hour = os.getenv("MORNING_PRIORITY_HOUR", "11")
        self.hour = hour if hour is not None else int(env_hour)
        self._last_boost_date: Optional[date] = None

    def is_past_boost_hour(self, now: Optional[datetime] = None) -> bool:
        current = now or datetime.now()
        return current.time() >= time(hour=self.hour)

    def should_boost(self, now: Optional[datetime] = None) -> bool:
        current = now or datetime.now()
        if not self.is_past_boost_hour(current):
            return False
        if self._last_boost_date == current.date():
            return False
        return True

    def mark_boosted(self, now: Optional[datetime] = None) -> None:
        current = now or datetime.now()
        self._last_boost_date = current.date()
        self.logger.info(
            f"[morning_boost] Утренний приоритет новых контрактов отмечен на {self._last_boost_date}"
        )
