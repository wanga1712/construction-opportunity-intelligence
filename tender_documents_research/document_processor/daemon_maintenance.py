import math
import os
from typing import Optional

import psutil


class DaemonMaintenance:
    """
    Класс, отвечающий за утилиты жизненного цикла демона:
    - очистка базы от зависших задач прошлого/этого запусков
    - привязка к ядрам процессора и настройка приоритета
    - контроль расходов памяти
    """

    def __init__(self, processing_backend, db, worker_id: int, memory_limit_bytes: int, logger):
        self.backend = processing_backend
        self.db = db
        self.worker_id = worker_id
        self.memory_limit_bytes = memory_limit_bytes
        self.logger = logger
        self.downloader = None

    def set_downloader(self, downloader):
        """Инжектим Downloader для lifecycle-операций."""
        self.downloader = downloader

    def reset_stale_tasks(self) -> None:
        """При запуске откатывает зависшие задачи своего воркера из processing → pending."""
        try:
            minutes = int(os.getenv("STALE_TASK_MINUTES", "60"))

            # 1. Сброс задач в очереди
            self.backend.queue.reset_stale(stale_minutes=minutes, worker_id=self.worker_id)

            # 2. Сброс статусов файлов в processed_documents (или file_processing_state)
            try:
                self.backend.state.reset_stale(worker_id=self.worker_id)
            except Exception as e:
                self.logger.warning(f"Ошибка сброса обработанных файлов: {e}")

            self.logger.info(f"[worker {self.worker_id}] Зависшие задачи и файлы сброшены")
        except Exception as e:
            self.logger.error(f"Failed to reset stale tasks: {e}")

    def requeue_error_tasks(self) -> Optional[int]:
        """Переводит задачи со статусом error → pending для повторной попытки."""
        try:
            return self.backend.queue.requeue_error_tasks()
        except Exception as e:
            self.logger.error(f"_requeue_error_tasks error: {e}")
            return None

    def cleanup_previous_run_data(self) -> None:
        try:
            self.backend.queue.cleanup_previous_run_data()
        except Exception as e:
            pass

    def apply_cpu_limits(self) -> None:
        """Ограничивает использование CPU через sched_setaffinity + nice (только Linux)."""
        try:
            n_cores = os.cpu_count() or 1
            frac_env = os.getenv("CPU_CORES_FRACTION")
            pct_env = os.getenv("CPU_LIMIT_PERCENT")
            frac = None
            if frac_env:
                frac = max(0.1, min(1.0, float(frac_env)))
            elif pct_env:
                p = max(10.0, min(100.0, float(pct_env)))
                frac = p / 100.0
            if frac is not None:
                allow = max(1, int(math.ceil(n_cores * frac)))
                cpus = list(range(allow))
                try:
                    os.sched_setaffinity(0, cpus)
                    self.logger.info(f"CPU affinity: используем {allow}/{n_cores} ядер")
                except Exception:
                    pass
                try:
                    os.nice(10)
                except Exception:
                    pass
        except Exception:
            pass


    def requeue_no_links_with_links(self) -> int:
        """Сбрасывает no_links -> pending для 44-fz контрактов, у которых появились ссылки."""
        try:
            if hasattr(self.backend.queue, 'requeue_no_links_with_links'):
                return self.backend.queue.requeue_no_links_with_links()
            return 0
        except Exception as e:
            self.logger.error(f"requeue_no_links_with_links error: {e}")
            return 0

    def ensure_daemon_alerts_table(self) -> None:
        try:
            self.db.execute_query("tender_monitor", """
                CREATE TABLE IF NOT EXISTS daemon_alerts (
                    id SERIAL PRIMARY KEY,
                    alert_type VARCHAR(50) NOT NULL DEFAULT 'general',
                    message TEXT NOT NULL,
                    worker_id INTEGER,
                    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        except Exception as e:
            self.logger.error(f"ensure_daemon_alerts_table error: {e}")

    def create_daemon_alert(self, alert_type: str, message: str) -> None:
        """Записывает алерт в daemon_alerts."""
        try:
            self.ensure_daemon_alerts_table()
            self.db.execute_query(
                "tender_monitor",
                "INSERT INTO daemon_alerts (alert_type, message, worker_id) VALUES (%s, %s, %s)",
                (alert_type, message, self.worker_id),
            )
        except Exception as e:
            self.logger.error(f"create_daemon_alert error: {e}")

    def over_memory_limit(self) -> bool:
        """Проверяет, превышен ли лимит памяти процесса."""
        try:
            proc = psutil.Process()
            used = proc.memory_info().rss
            return used > self.memory_limit_bytes
        except Exception:
            return False
