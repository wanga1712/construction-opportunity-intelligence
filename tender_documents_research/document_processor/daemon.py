import math
import os
import shutil
import time
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Optional

import psutil
from dotenv import load_dotenv

# Suppress InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from database_work.database_connection import DatabaseManager
from utils.logger_config import get_logger

from .downloader import Downloader
from .file_enhancer import FileEnhancer
from .matcher import KeywordMatcher
from .parser_factory import ParserFactory
from .parsers import ExcelParser
from .pdf_processor import parse_pdf_incremental
from .queue_manager import QueueManager
from .morning_priority_boost import MorningPriorityBoost
from .queue_populate_coordinator import QueuePopulateCoordinator
from .search_profile_config import load_search_profiles


from .task_pipeline import NoDocumentLinksError, TaskPipeline
from .daemon_maintenance import DaemonMaintenance


class DocumentProcessorDaemon:
    def __init__(self, db_configs: Optional[dict] = None):
        # Load env from .env in project root
        root_env = Path(__file__).parent.parent / ".env"
        load_dotenv(dotenv_path=root_env)
        
        # Load env from database_work/db_credintials.env
        env_path = Path(__file__).parent.parent / "database_work" / "db_credintials.env"
        load_dotenv(dotenv_path=env_path)
        print("daemon_init_start", flush=True)
        self.logger = get_logger()

        if db_configs is None:
            db_configs = {
                'tender_monitor': {
                    'host': os.getenv("DB_HOST_TENDER"),
                    'name': os.getenv("DB_DATABASE_TENDER"),
                    'user': os.getenv("DB_USER_TENDER"),
                    'password': os.getenv("DB_PASSWORD_TENDER"),
                    'port': os.getenv("DB_PORT_TENDER"),
                },
                'product_catalog_2': {
                    'host': os.getenv("DB_HOST_CATALOG"),
                    'name': os.getenv("DB_DATABASE_CATALOG"),
                    'user': os.getenv("DB_USER_CATALOG"),
                    'password': os.getenv("DB_PASSWORD_CATALOG"),
                    'port': os.getenv("DB_PORT_CATALOG"),
                },
            }

        self.db = DatabaseManager(db_configs)
        print("daemon_db_ready", flush=True)

        from .backends.factory import create_processing_backend as _cpb
        _backend_name = os.getenv("PROCESSING_BACKEND", "LEGACY")
        self.backend = _cpb(_backend_name, db=self.db)
        if _backend_name == "S13_V2":
            self.logger.info("[S13_V2] backend active")
            print("[S13_V2] backend active", flush=True)

        self.queue_manager = QueueManager(self.db)
        self.search_profiles = load_search_profiles()
        self.logger.info(f"Search profile config loaded: {self.search_profiles.summary()}")
        print(f"search_profiles: {self.search_profiles.summary()}", flush=True)
        self.downloader = Downloader(
            base_dir=Path(os.getenv("DOCUMENT_DOWNLOAD_DIR", "downloads")),
            db=self.db,
            state_repo=self.backend.state,
        )
        self.parser_factory = ParserFactory()
        print("daemon_init_before_matcher", flush=True)
        self.matcher = KeywordMatcher(self.db)
        print("daemon_init_after_matcher", flush=True)
        self.enhancer = FileEnhancer()
        self.worker_id = int(os.getenv("WORKER_ID", "1"))
        self.batch_size = int(os.getenv("BATCH_SIZE", "10"))
        self.sleep_seconds = int(os.getenv("DAEMON_SLEEP_SECONDS", "5"))
        self.memory_limit_bytes = int(os.getenv("MEMORY_LIMIT_BYTES", str(4 * 1024 ** 3)))
        self.temp_max_bytes = int(os.getenv("TEMP_DIR_MAX_BYTES", str(30 * 1024 ** 3)))
        
        self.failed_uploads_dir = Path(os.getenv("FAILED_UPLOADS_DIR", "failed_uploads"))
        self.failed_uploads_dir.mkdir(parents=True, exist_ok=True)
        
        # Подключение вынесенных модулей
        self.maintenance = DaemonMaintenance(getattr(self, "s13_backend", None), self.db, self.worker_id, self.memory_limit_bytes, self.logger)
        self.maintenance.set_downloader(self.downloader)
        
        self.pipeline = TaskPipeline(
            db=self.db,
            downloader=self.downloader,
            parser_factory=self.parser_factory,
            matcher=self.matcher,
            enhancer=self.enhancer,
            worker_id=self.worker_id,
            failed_uploads_dir=self.failed_uploads_dir,
            logger=self.logger,
            is_over_memory_limit=self.maintenance.over_memory_limit
        )
        self.morning_boost = MorningPriorityBoost()
        self.populate_coordinator = QueuePopulateCoordinator(
            self.queue_manager, self.morning_boost, self.logger
        )

        from .priority_recalculator import PriorityRecalculator
        self.priority_recalculator = PriorityRecalculator(
            db=self.db,
            logger=self.logger,
            required_workdays=int(os.getenv("REQUIRED_WORKDAYS", "2")),
            batch_size=int(os.getenv("PRIORITY_RECALC_BATCH", "500")),
        )
        self._last_full_recalc_date: Optional[str] = None
        self._last_crm_bridge_ts: float = 0.0

        try:
            self.maintenance.apply_cpu_limits()
        except Exception:
            pass
            
        self.maintenance.reset_stale_tasks()
        
        try:
            if os.getenv("CLEAN_PREVIOUS_RUN_DATA") == "1":
                self.maintenance.cleanup_previous_run_data()
                self.logger.info("Очистка данных прошлых запусков выполнена")
                print("cleanup_done", flush=True)
        except Exception:
            pass

        # Check OCR dependencies if enabled
        if os.getenv("ENABLE_OCR", "0") == "1":
            try:
                import pytesseract
                import pdf2image
                from PyPDF2 import PdfReader
                print("OCR dependencies verified", flush=True)
            except ImportError as e:
                self.logger.error(f"CRITICAL: OCR enabled but dependencies missing: {e}")
                print(f"CRITICAL: OCR enabled but dependencies missing: {e}", flush=True)
                raise

        # ── Backend already initialized above ──
        print("daemon_init_done", flush=True)

    # ------------------------------------------------------------------
    # Главный цикл
    # ------------------------------------------------------------------

    def run_once(self) -> bool:
        """
        Выполняет один цикл: пополнение очереди → скачивание → обработка.
        Возвращает True если были задачи, False если задач нет или ошибка.
        """
        self.logger.info("=== Старт цикла демона ===")
        print("run_once_start", flush=True)

        # ---- CRM → queue bridge (every hour, or first run) -----------------
        import time as _time
        crm_bridge_interval = int(os.getenv("CRM_BRIDGE_INTERVAL_SEC", "3600"))
        if os.getenv("ENABLE_CRM_BRIDGE", "1") == "1":
            if _time.monotonic() - self._last_crm_bridge_ts >= crm_bridge_interval:
                try:
                    from .crm_queue_bridge import CrmQueueBridge
                    bridge = CrmQueueBridge(self.db, self.logger)
                    bridge.run()
                    self._last_crm_bridge_ts = _time.monotonic()
                except Exception as exc:
                    self.logger.error(f"[crm_bridge] Ошибка: {exc}", exc_info=True)
        # ---------------------------------------------------------------------

        # ---- Priority recalculation ----------------------------------------
        # Full daily sweep at 06:00 (once per calendar day)
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            current_hour = datetime.now().hour
            if current_hour >= 6 and self._last_full_recalc_date != today_str:
                self.logger.info("[recalc] Ежедневный пересчёт приоритетов (06:00)...")
                print("priority_recalc_start", flush=True)
                n = self.priority_recalculator.run_full_sweep(force=False)
                self._last_full_recalc_date = today_str
                self.logger.info(f"[recalc] Готово, обновлено {n} задач")
                print(f"priority_recalc_done: {n}", flush=True)
            else:
                # Fast sweep: only rows due for recalc (next_priority_recalc_at <= NOW())
                n = self.priority_recalculator.run_full_sweep(force=False)
                if n:
                    self.logger.info(f"[recalc] Быстрый пересчёт: {n} задач")
        except Exception as exc:
            self.logger.error(f"[recalc] Ошибка пересчёта приоритетов: {exc}", exc_info=True)
        # -----------------------------------------------------------------------

        try:
            if os.getenv("REQUEUE_ERRORS") == "1":
                n = self.maintenance.requeue_error_tasks()
                if n is not None:
                    self.logger.info(f"Переочередили задач со статусом error: {n}")
        except Exception as _:
            pass

        try:
            if os.getenv("PROCESSING_BACKEND") == "S13_V2":
                q_map = self.backend.queue.get_queue_stats() if hasattr(self.backend.queue, 'get_queue_stats') else {}
            else:
                q_rows = self.db.execute_query(
                    "tender_monitor",
                    "SELECT status, COUNT(*) FROM document_processing_queue GROUP BY status",
                    fetch=True,
                ) or []
                q_map = {r[0]: int(r[1]) for r in q_rows}
            pending_count = q_map.get('pending', 0)
            msg = f"Queue status: pending={pending_count} processing={q_map.get('processing',0)} error={q_map.get('error',0)}"
            self.logger.info(msg)
            print(msg, flush=True)
        except Exception:
            pending_count = 0
            pass

        try:
            self.populate_coordinator.populate_if_needed(pending_count)
        except Exception as exc:
            self.logger.error(f"Ошибка при пополнении очереди: {exc}", exc_info=True)

        # ── S13_V2 claim branch ────────────────────────────────────────────────
        if os.getenv("PROCESSING_BACKEND") == "S13_V2":
            try:
                s13_tasks = self.backend.queue.claim_batch(
                    worker_id=self.worker_id,
                    batch_size=self.batch_size,
                )
            except Exception as exc:
                self.logger.error(f"[S13_V2] Queue claim failed: {exc}", exc_info=True)
                return False
            if not s13_tasks:
                self.logger.info("[S13_V2] No tasks, sleeping...")
                print("[S13_V2] No tasks, sleeping...", flush=True)
                return False
            for _t in s13_tasks:
                self._process_s13v2_task(_t)
            return True
        # ───────────────────────────────────────────────────────────────────────

        tasks = []
        try:
            self.logger.info("Забор батча задач из очереди...")
            tasks = self.queue_manager.get_next_batch(self.worker_id, self.batch_size)
        except Exception as exc:
            self.logger.error(f"Ошибка при получении батча задач: {exc}", exc_info=True)
            return False

        self.logger.info(f"Получено задач в батче: {len(tasks)}")
        print(f"Batch loaded: {len(tasks)} tasks", flush=True)
        if not tasks:
            self.logger.info("Задач нет, демон переходит в режим ожидания")
            print("No tasks, sleeping...", flush=True)
            return False

        # Pipeline: download(N+1) параллельно с parse(N)
        # Скачивание файлов ВНУТРИ одной закупки — до DOWNLOAD_PARALLEL потоков.
        # Между закупками — строго последовательно (не бить сервер).
        from concurrent.futures import Future

        download_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dl")
        pending_future: Optional[Future] = None
        pending_task = None

        # Запускаем скачивание первой задачи
        first_task = tasks[0]
        self.logger.info(f"[{first_task['id']}] Запуск скачивания: {first_task['contract_reg_number']}")
        print(f"[{first_task['id']}] Downloading {first_task['contract_reg_number']}...", flush=True)
        pending_future = download_executor.submit(
            self.pipeline.prefetch_task,
            first_task["id"], first_task["contract_reg_number"], first_task["table_source"],
        )
        pending_task = first_task

        for i, task in enumerate(tasks):
            task_id = task["id"]
            contract_reg_number = task["contract_reg_number"]
            table_source = task["table_source"]
            skip_processing = False

            # Ждём завершения скачивания текущей задачи
            if pending_future is not None and pending_task is not None and pending_task["id"] == task_id:
                try:
                    files = pending_future.result()
                    msg = f"[{task_id}] Download done: {len(files)} files"
                    self.logger.info(msg)
                    print(msg, flush=True)
                except NoDocumentLinksError as exc:
                    message = str(exc)
                    self.logger.warning(f"[{task_id}] {message}")
                    print(f"[{task_id}] NO_LINKS: {message}", flush=True)
                    self.queue_manager.mark_no_links(task_id, message)
                    files = []
                    skip_processing = True
                except Exception as exc:
                    msg = f"[{task_id}] Download error: {exc}"
                    self.logger.error(msg, exc_info=True)
                    print(msg, flush=True)
                    files = []
                pending_future = None
                pending_task = None
            else:
                # На случай если задача ещё не начинала скачиваться
                self.logger.info(f"[{task_id}] Скачивание (синхронно): {contract_reg_number}")
                print(f"[{task_id}] Downloading {contract_reg_number}...", flush=True)
                try:
                    files = self.pipeline.prefetch_task(task_id, contract_reg_number, table_source)
                    msg = f"[{task_id}] Download done: {len(files)} files"
                    self.logger.info(msg)
                    print(msg, flush=True)
                except NoDocumentLinksError as exc:
                    message = str(exc)
                    self.logger.warning(f"[{task_id}] {message}")
                    print(f"[{task_id}] NO_LINKS: {message}", flush=True)
                    self.queue_manager.mark_no_links(task_id, message)
                    files = []
                    skip_processing = True
                except Exception as exc:
                    msg = f"[{task_id}] Download error: {exc}"
                    self.logger.error(msg, exc_info=True)
                    print(msg, flush=True)
                    files = []

            # Запускаем скачивание СЛЕДУЮЩЕЙ задачи в фоне (пока парсим текущую)
            next_idx = i + 1
            if next_idx < len(tasks):
                next_task = tasks[next_idx]
                self.logger.info(f"[{next_task['id']}] Запуск фонового скачивания: {next_task['contract_reg_number']}")
                print(f"[{next_task['id']}] Background download {next_task['contract_reg_number']}...", flush=True)
                pending_future = download_executor.submit(
                    self.pipeline.prefetch_task,
                    next_task["id"], next_task["contract_reg_number"], next_task["table_source"],
                )
                pending_task = next_task

            if skip_processing:
                try:
                    self.downloader.cleanup(task_id)
                    self.logger.info(f"[{task_id}] Временные файлы удалены")
                except Exception:
                    pass
                continue

            # --- Парсинг текущей задачи ---
            print(f"[{task_id}] Processing {contract_reg_number} ({i+1}/{len(tasks)})...", end="", flush=True)

            if self.maintenance.over_memory_limit():
                msg = f"[{task_id}] Memory limit exceeded, breaking batch"
                self.logger.warning(msg)
                print(f" SKIP (MEM LIMIT)", flush=True)
                break

            try:
                self.logger.info(f"[{task_id}] Начало обработки задачи: {contract_reg_number}")
                proc_result = self.pipeline.process_task_with_files(
                    task_id, contract_reg_number, table_source, files
                )
                tender_id = self.pipeline.resolve_tender_id(
                    contract_reg_number, table_source
                )
                rows = []
                status_read_failed = False
                if tender_id is not None:
                    try:
                        rows = self.backend.state.list_file_statuses(
                            tender_id, table_source, raise_on_error=True
                        )
                    except Exception as status_exc:
                        status_read_failed = True
                        self.logger.error(
                            f"[{task_id}] completion status read failed: "
                            f"{type(status_exc).__name__}"
                        )

                decision = proc_result.apply_completion(
                    self.queue_manager,
                    task_id,
                    rows,
                    status_read_failed=status_read_failed,
                    task_eligible=tender_id is not None,
                )

                if not decision.allowed:
                    self.logger.warning(
                        f"[{task_id}] completion blocked: "
                        f"policy={decision.policy_version} "
                        f"reasons={decision.blocking_reasons} "
                        f"statuses={decision.observed_statuses}"
                    )
                    if "document_error_memory" in decision.blocking_reasons or (
                        "document_retryable_error" in decision.blocking_reasons
                    ):
                        print(" ERROR: completion blocked", flush=True)
                    else:
                        self.logger.info(
                            f"[{task_id}] Задача возвращена в очередь: "
                            f"{proc_result.summary_message()}"
                        )
                        print(" PENDING_RESUME", flush=True)
                else:
                    self.logger.info(f"[{task_id}] Задача завершена успешно")
                    print(" DONE", flush=True)
            except Exception as exc:
                message = str(exc)
                if "Не удалось скачать ни один документ" in message:
                    if not self.downloader.http_client.is_proxy_alive():
                        self.logger.error(f"[{task_id}] Стуннель (proxy) недоступен! Возврат в очередь и пауза.")
                        print(f" ERROR: STUNNEL DOWN! Pausing...", flush=True)
                        try:
                            self.db.execute_query(
                                "tender_monitor",
                                "UPDATE document_processing_queue SET status='pending', worker_id=NULL, started_at=NULL WHERE id=%s",
                                (task_id,)
                            )
                        except Exception:
                            pass
                        try:
                            self.downloader.cleanup(task_id)
                        except Exception:
                            pass
                        import time
                        time.sleep(30)
                        break

                self.logger.error(f"[{task_id}] Ошибка задачи: {message}", exc_info=True)
                print(f" ERROR: {message}", flush=True)
                try:
                    self.queue_manager.mark_error(task_id, message)
                except Exception:
                    self.logger.error(f"[{task_id}] Не удалось отметить как ошибочную", exc_info=True)
            finally:
                try:
                    self.downloader.cleanup(task_id)
                    self.logger.info(f"[{task_id}] Временные файлы удалены")
                except Exception:
                    pass

        download_executor.shutdown(wait=True)
        print("run_once_done", flush=True)
        return True

    def _process_s13v2_task(self, task: dict) -> None:
        """
        Process one S13_V2 task: download → parse+match → evidence → complete.
        """
        task_id = task["id"]
        procurement_id = task["procurement_id"]
        source_table = task.get("source_table", "")
        contract_number = task.get("contract_number", "") or ""
        backend = self.backend
        self.logger.info(
            f"[S13_V2][{task_id}] Processing procurement={procurement_id}"
        )
        print(f"[S13_V2][{task_id}] Start procurement={procurement_id}", flush=True)
        try:
            try:
                files = self.pipeline.prefetch_task(
                    task_id, contract_number, source_table
                )
            except Exception as dl_exc:
                msg = str(dl_exc)
                if "NoDocumentLinksError" in type(dl_exc).__name__:
                    backend.queue.mark_no_links(task_id, msg)
                    return
                raise
            if not files:
                backend.queue.mark_completed(task_id)
                return
            task_row = {
                "id": task_id,
                "contract_reg_number": contract_number,
                "table_source": source_table,
                "procurement_id": procurement_id,
            }
            self.pipeline.process_task_with_files(task_id, contract_number, source_table, files)
            try:
                backend.results.persist_evidence(
                    procurement_id=procurement_id,
                    queue_id=task_id,
                    match_id=0,
                    category_code="processed",
                    evidence_score=1.0,
                    match_count=len(files),
                    worker_id=self.worker_id,
                    next_stage="STRUCTURED_EXTRACTION_PENDING",
                )
            except Exception as ev_exc:
                self.logger.warning(
                    f"[S13_V2][{task_id}] Evidence write failed: {ev_exc}"
                )
            backend.queue.mark_completed(task_id)
            print(f"[S13_V2][{task_id}] COMPLETED", flush=True)
        except Exception as exc:
            msg = str(exc)[:1000]
            self.logger.error(
                f"[S13_V2][{task_id}] FAILED: {msg}", exc_info=True
            )
            print(f"[S13_V2][{task_id}] FAILED", flush=True)
            try:
                backend.queue.mark_failed(task_id, msg)
            except Exception:
                pass

    def run_forever(self) -> None:
        self.logger.info("Демон запущен в режиме непрерывной работы")
        while True:
            self.run_once()
            time.sleep(self.sleep_seconds)

# ------------------------------------------------------------------
# Точка входа
# ------------------------------------------------------------------

def main() -> None:
    print("daemon_start", flush=True)
    daemon = DocumentProcessorDaemon()
    try:
        daemon.populate_coordinator.populate_on_startup()
    except Exception as exc:
        daemon.logger.error(f"Ошибка стартового пополнения очереди: {exc}", exc_info=True)
    if os.getenv("RUN_ONCE") == "1":
        print("daemon_run_once_mode", flush=True)
        daemon.run_once()
    else:
        daemon.run_forever()


if __name__ == "__main__":
    main()
