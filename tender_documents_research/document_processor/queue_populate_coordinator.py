"""Координация пополнения очереди с учётом утреннего приоритета."""

from __future__ import annotations

from typing import Any

from .morning_priority_boost import MorningPriorityBoost
from .queue_manager import QueueManager


class QueuePopulateCoordinator:
    """Решает, когда и какие реестры подтягивать в очередь."""

    def __init__(
        self,
        queue_manager: QueueManager,
        morning_boost: MorningPriorityBoost,
        logger: Any,
        pending_threshold: int = 50,
    ) -> None:
        self.queue_manager = queue_manager
        self.morning_boost = morning_boost
        self.logger = logger
        self.pending_threshold = pending_threshold

    def populate_on_startup(self) -> int:
        """
        При старте/перезапуске демона — сразу подтянуть новые закупки (44/223 main).
        Если уже после MORNING_PRIORITY_HOUR, отмечаем дневной буст выполненным.
        """
        self.logger.info(
            "Старт демона: принудительное пополнение high-приоритета (новые 44/223)..."
        )
        print("Startup priority populate: high-priority registries", flush=True)
        if self.queue_manager.handles_high_priority():
            added = self.queue_manager.populate_high_priority(stop_after_first=False)
        else:
            added = self.queue_manager.populate_queue(
                tables=self.queue_manager.source_tables,
                stop_after_first=False,
            )
        if self.morning_boost.is_past_boost_hour():
            self.morning_boost.mark_boosted()
        self.logger.info(f"Стартовое пополнение завершено, добавлено задач: {added}")
        return added

    def _own_pending_count(self) -> int:
        """Число pending задач только для источников этого демона."""
        sources = self.queue_manager.allowed_table_sources
        if not sources:
            return 0
        try:
            placeholders = ", ".join(["%s"] * len(sources))
            rows = self.queue_manager.db.execute_query(
                "tender_monitor",
                f"SELECT COUNT(*) FROM document_processing_queue "
                f"WHERE status='pending' AND table_source IN ({placeholders})",
                tuple(sources),
                fetch=True,
            )
            return int(rows[0][0]) if rows else 0
        except Exception:
            return 0

    def populate_if_needed(self, pending_count: int) -> None:
        if not self.queue_manager.handles_high_priority():
            # Считаем только свои pending — иначе глобальная очередь open-демона
            # блокирует awarded-демон: он видит 500+ задач и не пополняет свои таблицы.
            own_pending = self._own_pending_count()
            self.logger.info(f"Awarded worker: own_pending={own_pending} (global={pending_count})")
            if own_pending < self.pending_threshold:
                self.logger.info("Пополнение очереди (awarded worker)...")
                self.queue_manager.populate_queue(
                    tables=self.queue_manager.source_tables,
                    stop_after_first=True,
                )
            return

        if self.morning_boost.should_boost():
            self.logger.info(
                f"Утренний приоритет ({self.morning_boost.hour}:00): "
                "принудительное пополнение новых контрактов 44/223..."
            )
            print("Morning priority boost: populate high-priority registries", flush=True)
            added = self.queue_manager.populate_high_priority(stop_after_first=False)
            self.morning_boost.mark_boosted()
            self.logger.info(f"Утренний буст завершён, добавлено задач: {added}")
            return

        if pending_count < self.pending_threshold:
            self.logger.info("Пополнение очереди задач...")
            self.queue_manager.populate_queue()
            self.logger.info("Пополнение очереди завершено")
            return

        # Очередь забита (часто awarded) — всё равно подтягиваем новые реестры
        self.logger.info(
            f"В очереди {pending_count} задач (>= {self.pending_threshold}): "
            f"подтягиваем только high-приоритет (новые 44/223)"
        )
        self.queue_manager.populate_high_priority(stop_after_first=False)
