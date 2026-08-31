import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from database_work.database_connection import DatabaseManager
from utils.logger_config import get_logger

from .http_client import HttpFileClient
from .concurrency_manager import DownloadCoordinator
from .archive_extractor import ArchiveExtractor
from .yandex_client import YandexDiskClient
from .file_skip_list import filter_links
from .resume_constants import STATUS_COMPLETED, STATUS_PENDING_RESUME, STATUS_PROCESSING
from .registry_contract_locator import RegistryContractLocator
from .documentation_links_loader import DocumentationLinksLoader
from .registry_tables import links_table_for_source
from .document_routing import DocumentRouter, RoutingContext

@dataclass
class DownloadFailure:
    source_link_id: Optional[int]
    source_url: str
    url_hash: str
    error_class: str
    http_status: Optional[int]
    error_message: str
    latency_ms: int

@dataclass
class DownloadBatchResult:
    source_links_count: int
    attempted_count: int
    downloaded_count: int
    skipped_count: int
    failed_count: int
    files: List[Path]
    failures: List[DownloadFailure]

    @property
    def transient_failed_count(self) -> int:
        return sum(1 for f in self.failures if f.error_class == "TRANSIENT")

    @property
    def permanent_failed_count(self) -> int:
        return sum(1 for f in self.failures if f.error_class == "PERMANENT")


class Downloader:
    """
    Главный класс-оркестратор для скачивания и распаковки файлов тендеров.
    Делегирует работу профильным клиентам.
    """
    def __init__(self, base_dir: Optional[Path] = None, db: Optional[DatabaseManager] = None, db_alias: str = "tender_monitor", state_repo=None):
        self.base_dir = base_dir or Path("downloads")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.approved_storage_root = self._resolve_approved_storage_root()

        if db is None:
            db_configs = {
                "tender_monitor": {
                    "host": os.getenv("DB_HOST_TENDER"),
                    "name": os.getenv("DB_DATABASE_TENDER"),
                    "user": os.getenv("DB_USER_TENDER"),
                    "password": os.getenv("DB_PASSWORD_TENDER"),
                    "port": os.getenv("DB_PORT_TENDER"),
                }
            }
            db = DatabaseManager(db_configs)

        self.db = db
        self.db_alias = db_alias
        self.logger = get_logger()

        # Инициализация подмодулей
        proxy_url = os.getenv("DOCUMENT_PROXY_URL")
        proxy_mode = os.getenv("DOCUMENT_PROXY_MODE", "endpoint")
        self.http_client = HttpFileClient(proxy_url, proxy_mode, self.logger)

        self.archive_extractor = ArchiveExtractor(self.logger)

        yandex_token = os.getenv("YANDEX_DISK_TOKEN")
        yandex_webdav_user = os.getenv("YANDEX_DISK_WEBDAV_USER")
        yandex_webdav_password = os.getenv("YANDEX_DISK_WEBDAV_PASSWORD")
        yandex_path_template = os.getenv("YANDEX_DISK_PATH_TEMPLATE", "{base}/{registry_type}/{contract_number}")
        self.yandex_client = YandexDiskClient(
            yandex_token, yandex_webdav_user, yandex_webdav_password,
            yandex_path_template, self.logger, self.http_client
        )

        self.state_repo = state_repo
        self.contract_locator = RegistryContractLocator(self.db, self.db_alias, self.logger)
        self.links_loader = DocumentationLinksLoader(self.db, self.db_alias)
        self.document_router = DocumentRouter()
        self.download_coordinator = DownloadCoordinator(self.db_alias)

    def _resolve_approved_storage_root(self) -> Optional[Path]:
        if os.getenv("PROCESSING_BACKEND") != "S13_V2":
            return None
        raw = os.getenv("DOCUMENT_STORAGE_ROOT")
        if not raw:
            raise RuntimeError("S13_V2 requires DOCUMENT_STORAGE_ROOT; refusing /opt downloads fallback")
        root = Path(raw).expanduser().resolve()
        if not root.is_absolute() or not root.exists() or not root.is_dir():
            raise RuntimeError(f"Invalid S13_V2 DOCUMENT_STORAGE_ROOT={root}")
        base = self.base_dir.expanduser().resolve()
        try:
            base.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"S13_V2 download base_dir must be under approved storage root: {base} not under {root}") from exc
        return root

    def _is_reusable_local_path(self, path: Path) -> bool:
        if not path.exists() or not path.is_file():
            return False
        approved_storage_root = getattr(self, "approved_storage_root", None)
        if approved_storage_root is None:
            return True
        try:
            path.resolve().relative_to(approved_storage_root)
            return True
        except ValueError:
            return False

    def get_links(self, contract_reg_number: str, table_source: str) -> List[Tuple[str, Optional[str]]]:
        """?????????? ?????? (url, file_name) ?? ??????? ??????????."""
        lookup = self.contract_locator.lookup(contract_reg_number, table_source)
        if not lookup.confirmed_ids:
            self.logger.debug(
                f"???????? {contract_reg_number} ?? ?????? ?? ? ????? ???? ??????? ({lookup.fz_type})"
            )
            return []

        links_table = links_table_for_source(table_source)
        result = self.links_loader.load_for_contract(
            links_table,
            contract_reg_number,
            list(lookup.confirmed_ids),
        )
        if lookup.canonical_table:
            self.logger.debug(
                f"???????? {contract_reg_number}: ?????={lookup.canonical_table} "
                f"(id={lookup.canonical_id}), ????={RegistryContractLocator.format_hits_summary(lookup.hits)}"
            )
        self.logger.debug(
            f"???????? ??????: {len(result)} ??? ????????? {contract_reg_number} ?? {links_table}"
        )

        result, skipped = filter_links(result)
        if skipped > 0:
            self.logger.info(f"????????? {skipped} ??????????? ?????? ??? {contract_reg_number} (???????? {len(result)})")

        context = self._load_routing_context(contract_reg_number, table_source)
        prioritized = self.document_router.prioritize_links(result, context)
        decision = self.document_router.detect(context)
        self.logger.info(
            f"??????????? ??????? {contract_reg_number}: mode={decision.mode} reason={decision.reason} title={context.title[:120]}"
        )
        return prioritized

    def _load_routing_context(self, contract_reg_number: str, table_source: str) -> RoutingContext:
        sql = f"""
            SELECT
                COALESCE(t.auction_name, '') AS auction_name,
                COALESCE(cco.main_code, cco.sub_code, '') AS okpd_code,
                COALESCE(cco.name, '') AS okpd_name
            FROM {table_source} t
            LEFT JOIN collection_codes_okpd cco ON cco.id = t.okpd_id
            WHERE t.contract_number = %s
            LIMIT 1
        """
        try:
            rows = self.db.execute_query(self.db_alias, sql, (contract_reg_number,), fetch=True) or []
        except Exception as exc:
            self.logger.warning(f"?? ??????? ????????? ???????? ??????? {contract_reg_number}: {exc}")
            rows = []
        if not rows:
            return RoutingContext(title='', okpd_code='', okpd_name='', contour_code='procurement')
        row = rows[0]
        return RoutingContext(
            title=str(row[0] or ''),
            okpd_code=str(row[1] or ''),
            okpd_name=str(row[2] or ''),
            contour_code='procurement',
        )

    @staticmethod
    def build_registry_link(table_source: str, contract_number: str) -> str:
        if "44" in table_source:
            return f"https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber={contract_number}"
        else:
            return f"https://zakupki.gov.ru/223/contract/public/contract/view/general-information.html?regNumber={contract_number}"

    def download_and_extract_legacy(self, task_id: int, links: List[Tuple[str, Optional[str]]], registry_type: Optional[str] = None, contract_number: Optional[str] = None, table_source: Optional[str] = None) -> List[Path]:
        res = self.download_and_extract(task_id, links, registry_type, contract_number, table_source)
        return res.files

    def download_and_extract(
        self,
        task_id: int,
        links: List[Any],
        registry_type: Optional[str] = None,
        contract_number: Optional[str] = None,
        table_source: Optional[str] = None,
        procurement_id: Optional[int] = None,
        source_id: Optional[int] = None,
    ) -> DownloadBatchResult:
        task_dir = self.base_dir / str(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)

        try:
            max_links = int(os.getenv("DOCUMENT_MAX_LINKS", "0"))
        except Exception:
            max_links = 0
        effective_links = links[:max_links] if max_links and max_links > 0 else links
        self.logger.info(f"[{task_id}] Начинаю скачивание {len(effective_links)} ссылок")

        raw_files: List[Path] = []
        failures: List[DownloadFailure] = []
        remote_dir, safe_prefix = self.yandex_client.build_remote_dir_and_prefix(registry_type, contract_number, None)

        resolved_source_id: Optional[int] = source_id
        if resolved_source_id is None and table_source and contract_number:
            resolved_source_id = self.contract_locator.resolve_tender_id(contract_number, table_source)
        # S13_V2 queue procurement_id is the local processing identity.
        # The registry/native tender id belongs in document_files.source_id.
        tender_id: Optional[int] = procurement_id if procurement_id is not None else resolved_source_id

        try:
            max_workers = int(os.getenv("DOWNLOAD_PARALLEL", "4"))
        except ValueError:
            max_workers = 4

        file_identity_map = {}

        # Этап 1: скачиваем ВСЕ файлы (без распаковки)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for item in effective_links:
                url = item[0]
                db_file_name = item[1]
                canonical_id = item[2] if len(item) > 2 else None
                phys_key = item[3] if len(item) > 3 else None

                futures.append(executor.submit(
                    self._process_single_link,
                    task_id, task_dir, url, db_file_name,
                    tender_id, table_source, remote_dir, safe_prefix, resolved_source_id,
                    canonical_id, phys_key
                ))

            for future in futures:
                try:
                    result_files, failure, canonical_id, phys_key, u_hash = future.result()
                    if result_files:
                        raw_files.extend(result_files)
                        for f_path in result_files:
                            file_identity_map[f_path.name] = (canonical_id, phys_key, u_hash)
                    if failure:
                        failures.append(failure)
                except Exception as exc:
                    self.logger.error(f"[{task_id}] Ошибка при параллельном скачивании файла: {exc}", exc_info=True)

        self.logger.info(f"[{task_id}] Скачано {len(raw_files)} файлов. Начинаю распаковку архивов...")

        # Этап 2: распаковка архивов ПОСЛЕ того как все части скачаны
        files: List[Path] = []
        for f in raw_files:
            canonical_id, phys_key, u_hash = file_identity_map.get(f.name, (None, None, None))
            if self.archive_extractor.is_archive(f):
                extracted = self.archive_extractor.extract_recursive(f, task_dir)
                if extracted:
                    files.extend(extracted)
                    self.logger.info(f"[{task_id}] Распаковано из {f.name}: {len(extracted)} файлов")
                    if tender_id is not None and table_source and self.state_repo:
                        self.state_repo.finalize_download_status(
                            tender_id, table_source, f.name, u_hash, True, None, local_path=f
                        )
                        # Записываем mapping для каждого распакованного из архива файла
                        for child in extracted:
                            self.state_repo.ensure_download_file(
                                task_id, tender_id, table_source, url="", url_hash=None, file_name=child.name,
                                source_id=resolved_source_id,
                                canonical_source_document_id=canonical_id,
                                physical_download_key=phys_key
                            )
                            self.state_repo.finalize_download_status(
                                tender_id, table_source, child.name, None, True, None, local_path=child
                            )
                else:
                    error_message = f"archive extraction failed: {f.name}"
                    self.logger.warning(
                        f"[{task_id}] Распаковка архива не дала файлов: {f.name}"
                    )
                    if tender_id is not None and table_source and self.state_repo:
                        self.state_repo.finalize_download_status(
                            tender_id,
                            table_source,
                            f.name,
                            u_hash,
                            False,
                            error_message,
                        )
            elif self._is_rar_part(f):
                # Части многотомного RAR (.r01, .r02, ...) — пропускаем,
                # они уже были использованы при распаковке .rar/.r00 точки входа
                continue
            else:
                files.append(f)

        self.logger.info(f"[{task_id}] Готово. Итого файлов для обработки: {len(files)}")
        return DownloadBatchResult(
            source_links_count=len(links),
            attempted_count=len(effective_links),
            downloaded_count=len(files),
            skipped_count=len(links) - len(effective_links),
            failed_count=len(failures),
            files=files,
            failures=failures
        )

    @staticmethod
    def _is_rar_part(path: Path) -> bool:
        """Возвращает True для частей многотомного RAR (.r00-.r99, .partN.rar), кроме .rar и .part1.rar"""
        import re
        suffix = path.suffix.lower()
        name = path.name.lower()

        # Старый формат (.r01, .r02...)
        if re.match(r'^\.r\d{2,}$', suffix):
            return True

        # Новый формат (.partN.rar)
        if ".part" in name and name.endswith(".rar"):
            # Если это .part1.rar (или part01.rar), то это НЕ "часть" в контексте пропуска, а точка входа
            is_entry = bool(re.search(r'\.part0*1\.rar$', name))
            return not is_entry

        return False

    def _process_single_link(self, task_id: int, task_dir: Path, url: str, db_file_name: Optional[str],
                             tender_id: Optional[int], table_source: Optional[str],
                             remote_dir: Optional[str], safe_prefix: Optional[str],
                             source_id: Optional[int] = None,
                             canonical_source_document_id: Optional[int] = None,
                             physical_download_key: Optional[str] = None) -> Tuple[List[Path], Optional[DownloadFailure], Optional[int], Optional[str], Optional[str]]:
        self.logger.debug(f"[{task_id}] Обработка ссылки: {url} (имя из БД: {db_file_name})")

        url_derived_name = self.http_client.sanitize_name(self.http_client.predict_filename(url))
        safe_predicted = self.http_client.sanitize_name(db_file_name) if db_file_name else url_derived_name

        import hashlib
        url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()

        if tender_id is not None and table_source and self.state_repo:
            self.state_repo.ensure_download_file(
                task_id, tender_id, table_source, url, url_hash, safe_predicted, source_id=source_id,
                canonical_source_document_id=canonical_source_document_id,
                physical_download_key=physical_download_key
            )
            status_row = self.state_repo.get_file_status(tender_id, table_source, safe_predicted, url_hash)
            current_status = status_row[0] if status_row else None

            # S13_V2 uses UPPERCASE, Legacy uses lowercase for processing. Normalize here for checks.
            check_status = current_status.upper() if current_status else None
            if check_status == "PROCESSING":
                self.logger.info(
                    f"[{task_id}] Файл в processing (возможно завис) — перескачиваю: {safe_predicted}"
                )
                self.state_repo.mark_file_status(
                    tender_id, table_source, safe_predicted, url_hash, current_status
                )
            if check_status == "COMPLETED":
                if os.getenv("REPROCESS_COMPLETED") != "1":
                    target_path = Path(status_row[1]) if len(status_row) > 1 and status_row[1] else task_dir / safe_predicted
                    if self._is_reusable_local_path(target_path):
                        self.logger.info(f"[{task_id}] Пропускаю файл (уже обработан и есть локально): {safe_predicted}")
                        self.state_repo.record_download_attempt(
                            task_id,
                            tender_id,
                            url,
                            url_hash,
                            0,
                            "SKIPPED",
                            bytes_received=target_path.stat().st_size,
                            duration_ms=0,
                        )
                        return [target_path], None, canonical_source_document_id, physical_download_key, url_hash
                    if target_path.exists():
                        self.logger.warning(
                            f"[{task_id}] S13 durable file is outside approved storage root; re-downloading: {target_path}"
                        )
                        self.state_repo.mark_file_status(tender_id, table_source, safe_predicted, url_hash, "PENDING")
                    else:
                        self.logger.info(f"[{task_id}] Файл в статусе COMPLETED, но локально отсутствует — перескачиваю: {safe_predicted}")
                else:
                    self.logger.info(f"[{task_id}] Файл обработан ранее, но разрешён REPROCESS_COMPLETED=1 — перезапускаю: {safe_predicted}")
                    self.state_repo.mark_file_status(tender_id, table_source, safe_predicted, url_hash, current_status)
            elif check_status == "PENDING_RESUME":
                self.logger.info(
                    f"[{task_id}] Повторное скачивание файла pending_resume: {safe_predicted}"
                )
                self.state_repo.mark_file_status(tender_id, table_source, safe_predicted, url_hash, current_status)

        ok_file: Optional[Path] = None
        is_rar_part = self._is_rar_part(Path(safe_predicted))

        # Use DB filename if available as the suggested filename for download
        suggested_name_for_download = self.http_client.sanitize_name(db_file_name) if db_file_name else None

        for attempt in range(2):
            attempt_number = attempt + 1
            attempt_start = time.monotonic()
            self.logger.debug(f"[{task_id}] Скачивание из источника (попытка {attempt_number}/2): {url}")
            local_path = self._download_single(task_dir, url, suggested_name_for_download)
            duration_ms = int((time.monotonic() - attempt_start) * 1000)
            if local_path is None:
                self.logger.warning(f"[{task_id}] Не удалось скачать: {url}")
                if tender_id is not None and table_source and self.state_repo:
                    self.state_repo.record_download_attempt(
                        task_id,
                        tender_id,
                        url,
                        url_hash,
                        attempt_number,
                        "FAILED",
                        error_class="TRANSIENT" if "zakupki.gov.ru" in url else "PERMANENT",
                        duration_ms=duration_ms,
                    )
                continue

            bytes_received = local_path.stat().st_size if local_path.exists() else None

            # Пропускаем валидацию для архивов и частей RAR — их нельзя "открыть" парсером
            if not is_rar_part and not self.archive_extractor.is_archive(local_path):
                from document_processor.file_validator import validate_open
                if not validate_open(local_path, self.logger):
                    self.logger.warning(f"[{task_id}] Файл не открывается: {local_path.name}. Переcкачивание…")
                    if tender_id is not None and table_source and self.state_repo:
                        self.state_repo.record_download_attempt(
                            task_id,
                            tender_id,
                            url,
                            url_hash,
                            attempt_number,
                            "FAILED",
                            error_class="PERMANENT",
                            bytes_received=bytes_received,
                            duration_ms=duration_ms,
                        )
                    try: local_path.unlink(missing_ok=True)
                    except Exception: pass
                    continue

            if db_file_name and local_path.name != safe_predicted and local_path.name == url_derived_name:
                target_path = task_dir / safe_predicted
                try:
                    local_path.rename(target_path)
                    local_path = target_path
                    self.logger.debug(f"[{task_id}] Файл переименован (URL → БД): {safe_predicted}")
                except Exception:
                    pass

            ok_file = local_path
            if tender_id is not None and table_source and self.state_repo:
                self.state_repo.record_download_attempt(
                    task_id,
                    tender_id,
                    url,
                    url_hash,
                    attempt_number,
                    "SUCCESS",
                    bytes_received=ok_file.stat().st_size if ok_file.exists() else bytes_received,
                    duration_ms=duration_ms,
                )
            break

        if not ok_file:
            self.logger.warning(f"[{task_id}] Не удалось получить валидный файл по ссылке: {url}")
            if tender_id is not None and table_source and self.state_repo:
                self.state_repo.finalize_download_status(tender_id, table_source, safe_predicted, url_hash, False, "download/validate failed")
            
            failure = DownloadFailure(
                source_link_id=None,
                source_url=url,
                url_hash=url_hash,
                error_class="TRANSIENT" if "zakupki.gov.ru" in url else "PERMANENT",
                http_status=None,
                error_message="download/validate failed",
                latency_ms=0
            )
            return [], failure, canonical_source_document_id, physical_download_key, url_hash

        if tender_id is not None and table_source and self.state_repo:
            self.state_repo.finalize_download_status(
                tender_id, table_source, safe_predicted, url_hash, True, None, ok_file
            )

        # Возвращаем файл как есть — распаковка будет в download_and_extract
        return [ok_file], None, canonical_source_document_id, physical_download_key, url_hash

    def _download_single(self, task_dir: Path, url: str, suggested_filename: Optional[str] = None) -> Optional[Path]:
        """
        Улучшенное скачивание с приоритетом прямых запросов
        """
        host = self.http_client.extract_host(url) or ""
        is_zakupki_filestore = "zakupki.gov.ru" in host and "/filestore/public/1.0/download/" in url

        # Задержка между запросами
        download_delay = float(os.getenv("DOWNLOAD_DELAY_SECONDS", "2.0"))
        max_retries = max(1, int(os.getenv("MAX_DOWNLOAD_RETRIES", "2")))
        bypass_proxy = os.getenv("BYPASS_PROXY_FOR_LARGE_FILES", "true").lower() == "true"

        proxy_url = os.getenv("DOCUMENT_PROXY_URL")
        proxy_mode = (os.getenv("DOCUMENT_PROXY_MODE") or "endpoint").lower()
        use_reverse_proxy = proxy_mode in ("reverse", "revproxy", "reverse_proxy")
        prefer_proxy = os.getenv("PREFER_STUNNEL_PROXY", "0") == "1" or (
            bool(proxy_url) and use_reverse_proxy
        )

        self.logger.info(f"Скачивание файла: {url}")

        # Если настроен reverse-stunnel — сначала прокси (не нужен DNS zakupki.gov.ru)
        if prefer_proxy and proxy_url:
            path = self.http_client.try_download_with_proxy(task_dir, url, suggested_filename)
            if path:
                self.logger.info(f"✅ Скачивание через прокси успешно: {path.name}")
                return path

        # Стратегия 1: Прямое скачивание (приоритет)
        if not prefer_proxy and (bypass_proxy or is_zakupki_filestore):
            for attempt in range(max_retries):
                try:
                    self.logger.debug(f"Попытка прямого скачивания {attempt + 1}/{max_retries}")
                    with self.download_coordinator.acquire_slot():
                        direct = self.http_client.try_download_direct(task_dir, url, suggested_filename)
                    if direct:
                        file_size = direct.stat().st_size
                        self.logger.info(f"✅ Прямое скачивание успешно: {direct.name} ({file_size} байт)")
                        return direct
                except Exception as e:
                    self.logger.warning(f"Прямое скачивание неуспешно (попытка {attempt + 1}): {e}")

                if attempt < max_retries - 1:
                    time.sleep(download_delay * (attempt + 1))

        # Стратегия 2: Через прокси (только для небольших файлов)
        max_proxy_size = int(os.getenv("MAX_PROXY_FILE_SIZE", "10485760"))

        if prefer_proxy:
            return None

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if "zakupki.gov.ru" in url:
                headers["Referer"] = "https://zakupki.gov.ru/"

            verify = self.http_client._get_verify_param()
            head_response = self.http_client.session.head(url, timeout=10, allow_redirects=True, headers=headers, verify=verify)
            content_length = head_response.headers.get("Content-Length")

            if content_length and int(content_length) > max_proxy_size:
                self.logger.info(f"Файл слишком большой для прокси ({content_length} байт), пропускаем прокси")
            else:
                self.logger.debug("Попытка скачивания через прокси")
                with self.download_coordinator.acquire_slot():
                    path = self.http_client.try_download_with_proxy(task_dir, url, suggested_filename)
                if path:
                    self.logger.info(f"✅ Скачивание через прокси успешно: {path.name}")
                    return path
        except Exception as e:
            self.logger.warning(f"Ошибка при скачивании через прокси: {e}")

        # Стратегия 3: HTML страницы и редиректы
        time.sleep(download_delay)
        if url.lower().endswith(".html") or "download.html" in url.lower() or url.split("?", 1)[0].lower().endswith(".html"):
            try:
                self.logger.debug("Попытка обработки HTML страницы")
                html_path = self.http_client.download_html_and_follow(task_dir, url)
                if html_path:
                    self.logger.info(f"✅ HTML обработка успешна: {html_path.name}")
                    return html_path
            except Exception as e:
                self.logger.warning(f"Ошибка обработки HTML: {e}")

        # Стратегия 4: Последняя попытка прямого скачивания
        if not bypass_proxy:  # Если еще не пробовали
            try:
                self.logger.debug("Финальная попытка прямого скачивания")
                with self.download_coordinator.acquire_slot():
                    direct_final = self.http_client.try_download_direct(task_dir, url, suggested_filename)
                if direct_final:
                    self.logger.info(f"✅ Финальное прямое скачивание успешно: {direct_final.name}")
                    return direct_final
            except Exception as e:
                self.logger.warning(f"Финальное прямое скачивание неуспешно: {e}")

        self.logger.error(f"❌ Не удалось скачать файл: {url}")
        return None

    def cleanup(self, task_id: int) -> None:
        try:
            path = self.base_dir / str(task_id)
            if path.exists() and path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                self.logger.info(f"[{task_id}] Временная папка очищена")
        except Exception:
            pass

    # Делегирование методов для совместимости со старым API (daemon.py использует их)
    def upload_matched_file(self, local_path: Path, registry_type: str, contract_number: str) -> Optional[str]:
        return self.yandex_client.upload_matched_file(local_path, registry_type, contract_number)

    def upload_error_file(self, local_path: Path, registry_type: str, contract_number: str, error_message: str) -> Optional[str]:
        return self.yandex_client.upload_error_file(local_path, registry_type, contract_number, error_message)
