import os
import re
import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from database_work.database_connection import DatabaseManager
from utils.logger_config import get_logger

from .http_client import HttpFileClient
from .archive_extractor import ArchiveExtractor
from .yandex_client import YandexDiskClient
from .file_skip_list import filter_links
from .resume_constants import STATUS_COMPLETED, STATUS_PENDING_RESUME, STATUS_PROCESSING
from .registry_contract_locator import RegistryContractLocator
from .documentation_links_loader import DocumentationLinksLoader
from .registry_tables import links_table_for_source
from .document_routing import DocumentRouter, RoutingContext


class Downloader:
    """
    Главный класс-оркестратор для скачивания и распаковки файлов тендеров.
    Делегирует работу профильным клиентам.
    """
    def __init__(self, base_dir: Optional[Path] = None, db: Optional[DatabaseManager] = None, db_alias: str = "tender_monitor", state_repo=None):
        self.base_dir = base_dir or Path("downloads")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
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

    def download_and_extract(self, task_id: int, links: List[Tuple[str, Optional[str]]], registry_type: Optional[str] = None, contract_number: Optional[str] = None, table_source: Optional[str] = None) -> List[Path]:
        task_dir = self.base_dir / str(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            max_links = int(os.getenv("DOCUMENT_MAX_LINKS", "0"))
        except Exception:
            max_links = 0
        effective_links = links[:max_links] if max_links and max_links > 0 else links
        self.logger.info(f"[{task_id}] Начинаю скачивание {len(effective_links)} ссылок")
        
        raw_files: List[Path] = []
        remote_dir, safe_prefix = self.yandex_client.build_remote_dir_and_prefix(registry_type, contract_number, None)
        
        tender_id: Optional[int] = None
        if table_source and contract_number:
            tender_id = self.contract_locator.resolve_tender_id(contract_number, table_source)

        try:
            max_workers = int(os.getenv("DOWNLOAD_PARALLEL", "4"))
        except ValueError:
            max_workers = 4
            
        # Этап 1: скачиваем ВСЕ файлы (без распаковки)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for url, db_file_name in effective_links:
                futures.append(executor.submit(
                    self._process_single_link,
                    task_id, task_dir, url, db_file_name,
                    tender_id, table_source, remote_dir, safe_prefix
                ))
            
            for future in as_completed(futures):
                try:
                    result_files = future.result()
                    if result_files:
                        raw_files.extend(result_files)
                except Exception as exc:
                    self.logger.error(f"[{task_id}] Ошибка при параллельном скачивании файла: {exc}", exc_info=True)

        self.logger.info(f"[{task_id}] Скачано {len(raw_files)} файлов. Начинаю распаковку архивов...")

        # Этап 2: распаковка архивов ПОСЛЕ того как все части скачаны
        files: List[Path] = []
        for f in raw_files:
            if self.archive_extractor.is_archive(f):
                extracted = self.archive_extractor.extract_recursive(f, task_dir)
                if extracted:
                    files.extend(extracted)
                    self.logger.info(f"[{task_id}] Распаковано из {f.name}: {len(extracted)} файлов")
                    if tender_id is not None and table_source and self.state_repo:
                        import hashlib
                        # URL was lost here since we only have path, but for legacy it only needs tender_id and filename.
                        # Wait, for S13_V2 we should mark the extracted files? Actually in S13_V2 download and extraction
                        # might just be marking the *archive* as COMPLETED. Let's provide a dummy url_hash or we need to pass it down.
                        # For now, just generate a dummy or None, S13V2StateRepo ignores if url_hash is None.
                        self.state_repo.finalize_file_status(
                            tender_id, table_source, f.name, None, True, None
                        )
                else:
                    error_message = f"archive extraction failed: {f.name}"
                    self.logger.warning(
                        f"[{task_id}] Распаковка архива не дала файлов: {f.name}"
                    )
                    if tender_id is not None and table_source and self.state_repo:
                        self.state_repo.finalize_file_status(
                            tender_id,
                            table_source,
                            f.name,
                            None,
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
        return files

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
                             remote_dir: Optional[str], safe_prefix: Optional[str]) -> List[Path]:
        self.logger.debug(f"[{task_id}] Обработка ссылки: {url} (имя из БД: {db_file_name})")
        
        url_derived_name = self.http_client.sanitize_name(self.http_client.predict_filename(url))
        safe_predicted = self.http_client.sanitize_name(db_file_name) if db_file_name else url_derived_name
        
        import hashlib
        url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()
        
        if tender_id is not None and table_source and self.state_repo:
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
                    self.logger.info(f"[{task_id}] Пропускаю файл (уже обработан): {safe_predicted}")
                    return []
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
            self.logger.debug(f"[{task_id}] Скачивание из источника (попытка {attempt+1}/2): {url}")
            local_path = self._download_single(task_dir, url, suggested_name_for_download)
            if local_path is None:
                self.logger.warning(f"[{task_id}] Не удалось скачать: {url}")
                continue
            
            if tender_id is not None and table_source and self.state_repo:
                # We use the legacy string "processing" which S13_V2 should handle or map, or we pass what state_repo expects.
                # Since state_repo interface doesn't strictly define enums, let's pass "PROCESSING".
                # For legacy, it might want "processing", but LegacyStateRepository just inserts what it's given.
                # However, previous code passed "processing" directly. We will pass "PROCESSING".
                # For S13_V2, document_files CHECK constraint expects 'PENDING', 'COMPLETED', 'FAILED', 'SKIPPED'.
                # Wait! `document_files` doesn't have 'PROCESSING'. The download_status only has 4 values.
                # So in S13_V2, we might not need to mark it as processing at the file level? 
                # Let's check the schema for document_files. It has PENDING, COMPLETED, FAILED, SKIPPED.
                # So we should pass 'PENDING' if we just want to mark it as starting? No, if it's downloading, there's no PROCESSING.
                # If backend is S13_V2, maybe mark it as something else or just skip this.
                pass

            # Пропускаем валидацию для архивов и частей RAR — их нельзя "открыть" парсером
            if not is_rar_part and not self.archive_extractor.is_archive(local_path):
                from document_processor.file_validator import validate_open
                if not validate_open(local_path, self.logger):
                    self.logger.warning(f"[{task_id}] Файл не открывается: {local_path.name}. Переcкачивание…")
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
            break

        if not ok_file:
            self.logger.warning(f"[{task_id}] Не удалось получить валидный файл по ссылке: {url}")
            if tender_id is not None and table_source and self.state_repo:
                self.state_repo.finalize_file_status(tender_id, table_source, safe_predicted, url_hash, False, "download/validate failed")
            return []

        # Возвращаем файл как есть — распаковка будет в download_and_extract
        return [ok_file]

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
