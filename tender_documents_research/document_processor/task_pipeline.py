import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

from document_processor.parse_utils import get_rich_parser, parse_file_with_meta, supports_rich_meta
from document_processor.pdf_processor import parse_pdf_incremental
from document_processor.file_skip_list import should_skip_file
from document_processor.resume_constants import max_resume_attempts
from document_processor.task_completion import can_complete_tender_files
from document_processor.task_result import TaskProcessResult
from document_processor.registry_contract_locator import RegistryContractLocator


class NoDocumentLinksError(RuntimeError):
    """Raised when a queued contract has no document links in the database."""


class TaskPipeline:
    """
    Класс, отвечающий за полный цикл обработки одной задачи (одного контракта):
    - предзагрузка списка файлов
    - парсинг файлов (через ParserFactory и pdf_processor)
    - поиск совпадений (KeywordMatcher)
    - подсветка и переименование (FileEnhancer)
    - загрузка результатов на Я.Диск (через Downloader)
    - сохранение статистики в БД
    """

    def __init__(
        self,
        db,
        downloader,
        parser_factory,
        matcher,
        enhancer,
        worker_id: int,
        failed_uploads_dir: Path,
        logger,
        is_over_memory_limit,
    ):
        self.db = db
        self.downloader = downloader
        self.parser_factory = parser_factory
        self.matcher = matcher
        self.enhancer = enhancer
        self.worker_id = worker_id
        self.failed_uploads_dir = failed_uploads_dir
        self.logger = logger
        self.is_over_memory_limit = is_over_memory_limit
        self.contract_locator = RegistryContractLocator(db, "tender_monitor", logger)

    def resolve_tender_id(self, contract_reg_number: str, table_source: str) -> Optional[int]:
        try:
            return self.contract_locator.resolve_tender_id(
                contract_reg_number, table_source
            )
        except Exception as e:
            self.logger.error(f"resolve_tender_id error: {e}")
            return None

    def resolve_registry_label(self, table_source: str) -> str:
        if "223" in table_source:
            return "223fz"
        return "44fz"

    def save_failed_upload(self, local_path: Path, reason: str = "unknown") -> None:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = f"{timestamp}_{local_path.name}"
            dest = self.failed_uploads_dir / safe_name
            shutil.copy2(local_path, dest)
            self.logger.info(f"Сохранен файл с ошибкой загрузки: {dest} (причина: {reason})")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить файл с ошибкой загрузки {local_path}: {e}")

    def prefetch_task(
        self,
        task_id: int,
        contract_reg_number: str,
        table_source: str,
        procurement_id: Optional[int] = None,
        source_id: Optional[int] = None,
    ):
        self.logger.info(f"[{task_id}] Получение ссылок для {contract_reg_number}...")
        try:
            if os.getenv("LOG_REGISTRY_LINK") == "1":
                link = self.downloader.build_registry_link(table_source, contract_reg_number)
                self.logger.info(f"[{task_id}] Карточка контракта: {link}")
                print(f"[{task_id}] Registry: {link}", flush=True)
        except Exception:
            pass
        links = self.downloader.get_links(contract_reg_number, table_source)
        if not links:
            message = f"Нет ссылок документов для {contract_reg_number} в {table_source}"
            self.logger.warning(f"[{task_id}] {message}")
            raise NoDocumentLinksError(message)
        max_links = int(os.getenv("DOCUMENT_MAX_LINKS", "0") or 0)
        if max_links > 0:
            links = links[:max_links]
        self.logger.info(f"[{task_id}] Найдено ссылок: {len(links)}, начинаем скачивание...")
        registry_label = self.resolve_registry_label(table_source)
        batch = self.downloader.download_and_extract(
            task_id,
            links,
            registry_type=registry_label,
            contract_number=contract_reg_number,
            table_source=table_source,
            procurement_id=procurement_id,
            source_id=source_id,
        )
        self.logger.info(f"[{task_id}] Скачано файлов для обработки: {len(batch.files)}")
        return batch

    def _file_is_resuming(
        self, tender_id: Optional[int], table_source: str, file_name: str
    ) -> bool:
        if tender_id is None:
            return False
        cursor = self.downloader.state_repo.get_progress_cursor(
            tender_id, table_source, file_name
        )
        if cursor and cursor > 0:
            return True
        row = self.downloader.state_repo.get_processed_status(
            tender_id, table_source, file_name
        )
        return bool(row and row[0] == "pending_resume")

    def _handle_partial_pdf(
        self,
        task_id: int,
        tender_id: int,
        table_source: str,
        file_name: str,
        result: TaskProcessResult,
    ) -> bool:
        """
        Обрабатывает неполный PDF. Возвращает True, если файл переведён в error_memory.
        """
        cursor = self.downloader.state_repo.get_progress_cursor(
            tender_id, table_source, file_name
        )
        attempts = self.downloader.state_repo.mark_pending_resume(
            tender_id,
            table_source,
            file_name,
            cursor,
            error_message="Прервано по лимиту памяти, ожидает продолжения",
        )
        if attempts >= max_resume_attempts():
            msg = (
                f"Исчерпаны попытки возобновления ({attempts}) "
                f"на странице progress_cursor={cursor}"
            )
            self.downloader.state_repo.mark_error_memory(
                tender_id, table_source, file_name, msg
            )
            result.error_memory_files.append(file_name)
            self.logger.error(f"[{task_id}] {file_name}: {msg}")
            return True
        result.pending_resume_files.append(file_name)
        self.logger.warning(
            f"[{task_id}] {file_name}: pending_resume cursor={cursor} "
            f"attempt={attempts}/{max_resume_attempts()}"
        )
        return False

    def process_task_with_files(
        self,
        task_id: int,
        contract_reg_number: str,
        table_source: str,
        files: list[Path],
    ) -> TaskProcessResult:
        self.logger.info(f"[{task_id}] Получено файлов: {len(files)}")
        if not files:
            tender_id = self.resolve_tender_id(contract_reg_number, table_source)
            if tender_id is not None:
                rows = self.downloader.state_repo.list_file_statuses(
                    tender_id, table_source
                )
                if rows and can_complete_tender_files(rows):
                    self.logger.info(
                        f"[{task_id}] Новых файлов нет, но все уже completed — считаем задачу готовой"
                    )
                    return TaskProcessResult()
            raise RuntimeError("Не удалось скачать ни один документ")

        tender_id = self.resolve_tender_id(contract_reg_number, table_source)
        total_files = len(files)
        total_size = sum(p.stat().st_size for p in files if p.exists())
        result = TaskProcessResult()
        processed_names: Set[str] = set()

        for path in files:
            if should_skip_file(path.name):
                self.logger.info(f"[{task_id}] Пропуск файла (skip list): {path.name}")
                continue

            file_start_time = time.monotonic()
            self.logger.info(f"[{task_id}] Обработка файла: {path.name}")
            processed_names.add(path.name)
            resuming = self._file_is_resuming(tender_id, table_source, path.name)

            try:
                text = ""
                finished_fully = True
                line_meta = None

                use_pdf_ocr = (
                    path.suffix.lower() == ".pdf"
                    and os.getenv("ENABLE_OCR", "0") == "1"
                    and os.getenv("ENABLE_OCR_PAGED", "1") == "1"
                )
                if use_pdf_ocr:
                    text, line_meta, finished_fully = parse_pdf_incremental(
                        path,
                        tender_id,
                        table_source,
                        self.downloader,
                        self.logger,
                        self.is_over_memory_limit,
                    )
                    if text is None:
                        raise RuntimeError(
                            "Ошибка при открытии/чтении PDF "
                            "(возможно файл поврежден или зашифрован)"
                        )
                else:
                    parser = (
                        get_rich_parser(self.parser_factory, path)
                        if supports_rich_meta(path)
                        else self.parser_factory.get_parser(path)
                    )
                    if parser is None:
                        self.logger.warning(
                            f"[{task_id}] Пропуск файла (неподдерживаемый формат): {path.name}"
                        )
                        continue
                    text, line_meta = parse_file_with_meta(parser, path)

                if not finished_fully:
                    if tender_id is not None:
                        became_error = self._handle_partial_pdf(
                            task_id, tender_id, table_source, path.name, result
                        )
                        if became_error:
                            if text:
                                matches = self.matcher.process_text(
                                    text, line_meta=line_meta
                                )
                                if matches:
                                    self.matcher.save_matches(
                                        tender_id,
                                        table_source,
                                        path.name,
                                        matches,
                                        worker_id=self.worker_id,
                                        processing_time_seconds=round(
                                            time.monotonic() - file_start_time, 3
                                        ),
                                        total_files_processed=total_files,
                                        total_size_bytes=total_size,
                                        folder_name=contract_reg_number,
                                        merge_existing=True,
                                    )
                            continue
                    else:
                        result.pending_resume_files.append(path.name)

                    if text:
                        matches = self.matcher.process_text(text, line_meta=line_meta)
                        if matches and tender_id is not None:
                            self.matcher.save_matches(
                                tender_id,
                                table_source,
                                path.name,
                                matches,
                                worker_id=self.worker_id,
                                processing_time_seconds=round(
                                    time.monotonic() - file_start_time, 3
                                ),
                                total_files_processed=total_files,
                                total_size_bytes=total_size,
                                folder_name=contract_reg_number,
                                merge_existing=True,
                            )
                    continue

                if not text:
                    self.logger.warning(
                        f"[{task_id}] Файл {path.name} пуст после парсинга, совпадений не будет"
                    )
                    matches = []
                else:
                    matches = self.matcher.process_text(text, line_meta=line_meta)

                if not matches:
                    if tender_id is not None:
                        self.downloader.state_repo.finalize_processing_status(
                            tender_id, table_source, path.name, False, None
                        )
                    self.logger.info(
                        f"[{task_id}] В файле {path.name} совпадений не найдено"
                    )
                    print(f"[{task_id}] NO_MATCHES: {path.name}", flush=True)
                    continue

                self.logger.info(
                    f"[{task_id}] Найдено {len(matches)} совпадений в файле {path.name}"
                )

                try:
                    if self.enhancer.highlight_matches(path, matches):
                        self.logger.info(f"[{task_id}] Файл {path.name} подсвечен")
                except Exception as e:
                    self.logger.error(f"[{task_id}] Ошибка подсветки {path.name}: {e}")

                try:
                    new_path = self.enhancer.rename_file(path, contract_reg_number)
                    if new_path != path:
                        self.logger.info(
                            f"[{task_id}] Переименован: {path.name} → {new_path.name}"
                        )
                        path = new_path
                except Exception as e:
                    self.logger.error(f"[{task_id}] Ошибка переименования {path.name}: {e}")

                if tender_id is None:
                    self.logger.warning(
                        f"[{task_id}] Не удалось определить tender_id для "
                        f"{contract_reg_number}, сохранение матчей пропускается"
                    )
                    continue

                print(
                    f"[{task_id}] MATCHES {len(matches)}: {path.name}",
                    flush=True,
                )
                self.downloader.state_repo.finalize_processing_status(
                    tender_id, table_source, path.name, True, None
                )

                processing_time = round(time.monotonic() - file_start_time, 3)
                self.matcher.save_matches(
                    tender_id,
                    table_source,
                    path.name,
                    matches,
                    yandex_path=None,
                    worker_id=self.worker_id,
                    processing_time_seconds=processing_time,
                    total_files_processed=total_files,
                    total_size_bytes=total_size,
                    folder_name=contract_reg_number,
                    merge_existing=resuming,
                )
                self.logger.info(
                    f"[{task_id}] Совпадения сохранены в БД за {processing_time}с"
                )

            except Exception as e:
                error_message = str(e)
                self.logger.error(
                    f"[{task_id}] Ошибка при обработке файла {path.name}: {error_message}",
                    exc_info=True,
                )
                print(f"[{task_id}] ERROR: {path.name}", flush=True)

                if tender_id is not None:
                    self.downloader.state_repo.finalize_processing_status(
                        tender_id, table_source, path.name, False, error_message
                    )
                    result.retryable_error_files.append(path.name)
                    self.matcher.save_file_error(
                        tender_id,
                        table_source,
                        path.name,
                        error_message,
                        worker_id=self.worker_id,
                        folder_name=contract_reg_number,
                    )

        if tender_id is not None:
            rows = self.downloader.state_repo.list_file_statuses(tender_id, table_source)
            for name, status in rows:
                if status == "pending_resume" and name not in result.pending_resume_files:
                    result.pending_resume_files.append(name)
            if not can_complete_tender_files(rows, processed_in_run=processed_names):
                if not result.pending_resume_files:
                    blocking = [
                        f"{n}:{s}"
                        for n, s in rows
                        if s in ("processing", "pending_resume", "error")
                    ]
                    self.logger.warning(
                        f"[{task_id}] Закупка не готова к завершению: {blocking}"
                    )

        return result
