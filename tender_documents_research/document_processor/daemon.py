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
from .pipelines.s13_v2_pipeline import S13V2Pipeline
from .daemon_maintenance import DaemonMaintenance
from .task_completion import can_complete_tender_files
from .match_engine import MatchEngine
from .dto import ProcessingOutcome
from .backends.s13_persistence import S13V2TaskPersistenceService

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
            if os.getenv("PROCESSING_BACKEND", "LEGACY") in ("S13_V2", "S13_V4"):
                db_configs['document_intelligence'] = {
                    'host': os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
                    'name': os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
                    'user': os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
                    'password': os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
                    'port': os.getenv("S13_DOCUMENT_DB_PORT", "5432"),
                }

        self.db = DatabaseManager(db_configs)
        # ─────────────────────────────────────────────────────────────────
        # PROCESSING_BACKEND=LEGACY (or unset) → legacy path unchanged
        # PROCESSING_BACKEND=S13_V2           → document_intelligence backend
        from .backends.factory import create_processing_backend as _cpb
        _backend_name = os.getenv("PROCESSING_BACKEND", "LEGACY")
        self.s13_backend = _cpb(_backend_name, getattr(self, "db", None))
        if _backend_name in ("S13_V2", "S13_V4"):
            self.logger.info(f"[{_backend_name}] backend active")
            print(f"[{_backend_name}] backend active", flush=True)
        # ─────────────────────────────────────────────────────────────────

        print("daemon_db_ready", flush=True)
        self.queue_manager = QueueManager(getattr(self, "s13_backend", None), self.db)
        self.search_profiles = load_search_profiles()
        self.logger.info(f"Search profile config loaded: {self.search_profiles.summary()}")
        print(f"search_profiles: {self.search_profiles.summary()}", flush=True)
        download_base_dir = self._resolve_download_base_dir(_backend_name)
        # _db_alias must always target tender_monitor for registry/link tables which reside on S7
        _db_alias = "tender_monitor"
        self.downloader = Downloader(
            base_dir=download_base_dir,
            db=self.db,
            db_alias=_db_alias,
            state_repo=self.s13_backend.state if self.s13_backend else None,
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
        self.maintenance = DaemonMaintenance(getattr(self, 's13_backend', None), self.db, self.worker_id, self.memory_limit_bytes, self.logger)
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
        self.s13_pipeline = S13V2Pipeline(
            parser_factory=self.parser_factory,
            downloader=self.downloader,
            logger=self.logger,
            is_over_memory_limit=self.maintenance.over_memory_limit
        )
        # S13_V2 must use the pure DTO match engine, but its configuration
        # comes from the already-loaded CRM taxonomy KeywordMatcher.  Passing
        # DatabaseManager here used to make every parsed file fail inside
        # MatchEngine.process_text(), leaving zero successfully processed files.
        self.match_engine = MatchEngine(
            keywords=list(self.matcher.keywords),
            stop_phrases=list(self.matcher.stop_phrases),
            custom_thresholds=dict(self.matcher.custom_thresholds),
            min_score=self.matcher.min_score,
            keyword_meta=dict(self.matcher.keyword_meta),
        )
        gen = "S13_V4_EXHAUSTIVE_CONTEXT" if _backend_name == "S13_V4" else "S13_V2"
        self.s13_persistence = S13V2TaskPersistenceService(self.db, pipeline_generation=gen)
        self.morning_boost = MorningPriorityBoost()
        self.populate_coordinator = QueuePopulateCoordinator(
            self.queue_manager, self.morning_boost, self.logger
        )

        try:
            self.maintenance.apply_cpu_limits()
        except Exception:
            pass

        self.maintenance.reset_stale_tasks()

    def _resolve_download_base_dir(self, backend_name: str) -> Path:
        """Resolve download root. S13_V2/V4 must fail closed instead of falling back to /opt."""
        if backend_name in ("S13_V2", "S13_V4"):
            storage_root_raw = os.getenv("DOCUMENT_STORAGE_ROOT")
            if not storage_root_raw:
                raise RuntimeError(f"{backend_name} requires DOCUMENT_STORAGE_ROOT; refusing /opt downloads fallback")
            storage_root = Path(storage_root_raw).expanduser().resolve()
            if not storage_root.is_absolute() or not storage_root.exists() or not storage_root.is_dir():
                raise RuntimeError(f"Invalid {backend_name} DOCUMENT_STORAGE_ROOT={storage_root}")
            configured_download = os.getenv("DOCUMENT_DOWNLOAD_DIR")
            download_root = Path(configured_download).expanduser().resolve() if configured_download else storage_root / "downloads-open"
            try:
                download_root.relative_to(storage_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"{backend_name} DOCUMENT_DOWNLOAD_DIR must be under DOCUMENT_STORAGE_ROOT: {download_root} not under {storage_root}"
                ) from exc
            download_root.mkdir(parents=True, exist_ok=True)
            return download_root
        return Path(os.getenv("DOCUMENT_DOWNLOAD_DIR", "downloads"))

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

        try:
            if os.getenv("REQUEUE_ERRORS") == "1":
                n = self.maintenance.requeue_error_tasks()
                if n is not None:
                    self.logger.info(f"Переочередили задач со статусом error: {n}")
        except Exception as _:
            pass

        try:
            if self.s13_backend is not None:
                q_rows = self.s13_backend.queue.get_queue_stats(self.worker_id)
                q_map = {r["status"]: r["count"] for r in q_rows}
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
        except Exception as exc:
            self.logger.warning(f"Could not fetch queue stats: {exc}")
            pending_count = 0
            pass

        try:
            pass # bypassed
        except Exception as exc:
            self.logger.error(f"Ошибка при пополнении очереди: {exc}", exc_info=True)

        # ── S13_V2 claim branch ────────────────────────────────────────────────
        if self.s13_backend is not None:
            if hasattr(self.downloader, 'download_coordinator') and self.downloader.download_coordinator.is_download_subsystem_busy():
                self.logger.info("[S13_V2] Download subsystem is fully busy. Pausing before claim.")
                print("[S13_V2] Download subsystem busy, sleeping...", flush=True)
                return False

            try:
                _lanes_raw = (os.getenv("QUEUE_LANES") or "").strip()
                _lanes = [x.strip() for x in _lanes_raw.split(",") if x.strip()] or None
                s13_tasks = self.s13_backend.queue.claim_batch(
                    worker_id=self.worker_id,
                    batch_size=self.batch_size,
                    queue_lanes=_lanes,
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
                    batch = pending_future.result()
                    files = batch.files
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
                    batch = self.pipeline.prefetch_task(task_id, contract_reg_number, table_source)
                    files = batch.files
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

                if task.get("pipeline_generation") == "S13_V2":
                    proc_result = self.s13_pipeline.process_task(
                        queue_id=task_id,
                        procurement_id=task["procurement_id"],
                        contract_reg_number=contract_reg_number,
                        table_source=table_source,
                        files=files,
                        match_engine=self.match_engine
                    )

                    if proc_result.outcome == ProcessingOutcome.FAILED:
                        self.s13_backend.queue.mark_failed(task_id, proc_result.error_message)
                        print(f" ERROR: {proc_result.error_message}", flush=True)
                    elif proc_result.files and all(
                        file_result.status == "SKIPPED" for file_result in proc_result.files
                    ):
                        self.s13_backend.queue.mark_no_links(
                            task_id, "NO_RESEARCHABLE_DOCUMENT_LINKS"
                        )
                        print(" NO_RESEARCHABLE_DOCUMENT_LINKS", flush=True)
                    else:
                        self.s13_persistence.persist_task_result(proc_result)
                        self.logger.info(f"[{task_id}] S13_V2 Задача завершена успешно (atomically persisted)")
                        print(" DONE (S13_V2)", flush=True)
                else:
                    # Legacy execution path
                    proc_result = self.pipeline.process_task_with_files(
                        task_id, contract_reg_number, table_source, files
                    )
                    tender_id = self.pipeline.resolve_tender_id(
                        contract_reg_number, table_source
                    )
                    db_ok = True
                    if tender_id is not None:
                        rows = self.downloader.state_repo.list_file_statuses(
                            tender_id, table_source
                        )
                        db_ok = can_complete_tender_files(rows)

                    if proc_result.needs_requeue or not db_ok:
                        self.queue_manager.mark_requeue_pending(
                            task_id, proc_result.summary_message() or "incomplete"
                        )
                        self.logger.info(
                            f"[{task_id}] Задача возвращена в очередь: "
                            f"{proc_result.summary_message()}"
                        )
                        print(" PENDING_RESUME", flush=True)
                    elif proc_result.retryable_error_files:
                        self.queue_manager.mark_error(
                            task_id, proc_result.summary_message()
                        )
                        print(f" ERROR: {proc_result.summary_message()}", flush=True)
                    else:
                        self.queue_manager.mark_completed(task_id)
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
        backend = self.s13_backend
        self.logger.info(
            f"[S13_V2][{task_id}] Processing procurement={procurement_id}"
        )
        print(f"[S13_V2][{task_id}] Start procurement={procurement_id}", flush=True)
        try:
            try:
                batch = self.pipeline.prefetch_task(
                    task_id,
                    contract_number,
                    source_table,
                    procurement_id=procurement_id,
                    source_id=task.get("source_id"),
                )
                files = batch.files
                
                if batch.failed_count > 0:
                    has_transient = any((f.error_class or "").upper() == "TRANSIENT" for f in batch.failures)
                    if has_transient:
                        msg = f"Transient download errors: {batch.failed_count}. Requeueing."
                        self.logger.warning(f"[S13_V2][{task_id}] {msg}")
                        backend.queue.mark_pending(task_id)
                        return
                    elif len(files) == 0:
                        msg = f"All downloads failed permanently."
                        self.logger.error(f"[S13_V2][{task_id}] {msg}")
                        backend.queue.mark_failed(task_id, msg)
                        return
            except Exception as dl_exc:
                msg = str(dl_exc)
                if "NoDocumentLinksError" in type(dl_exc).__name__:
                    backend.queue.mark_no_links(task_id, msg)
                    return
                raise
            if not files:
                attempted = 0
                try:
                    attempted = int(getattr(batch, "attempted_count", 0) or getattr(batch, "source_links_count", 0) or 0)
                except Exception:
                    attempted = 0
                if attempted > 0:
                    fail_n = 0
                    try:
                        fail_n = int(getattr(batch, "failed_count", 0) or 0)
                    except Exception:
                        fail_n = 0
                    msg = (
                        f"DOWNLOAD_FAILED: resolved_links={attempted} "
                        f"downloaded=0 failed={fail_n}"
                    )
                    self.logger.error(f"[S13_V2][{task_id}] {msg}")
                    backend.queue.mark_failed(task_id, msg)
                    return
                backend.queue.mark_no_links(task_id, "No researchable document links")
                return
            proc_result = self.s13_pipeline.process_task(
                queue_id=task_id,
                procurement_id=procurement_id,
                contract_reg_number=contract_number,
                table_source=source_table,
                files=files,
                match_engine=self.match_engine,
            )
            if proc_result.outcome == "FAILED":
                backend.queue.mark_failed(task_id, proc_result.error_message)
                return
            elif proc_result.files and all(file_result.status == "SKIPPED" for file_result in proc_result.files):
                backend.queue.mark_no_links(task_id, "NO_RESEARCHABLE_DOCUMENT_LINKS")
                return
            self.s13_persistence.persist_task_result(proc_result)
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
        pass # bypassed for S13
    except Exception as exc:
        daemon.logger.error(f"Ошибка стартового пополнения очереди: {exc}", exc_info=True)
    if os.getenv("RUN_ONCE") == "1":
        print("daemon_run_once_mode", flush=True)
        daemon.run_once()
    else:
        daemon.run_forever()


if __name__ == "__main__":
    main()
