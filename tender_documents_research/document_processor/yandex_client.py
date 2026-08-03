import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests


def yandex_disk_disabled() -> bool:
    """Яндекс.Диск не используется в проекте (deprecated с 2026-07)."""
    return True


class YandexDiskClient:
    """
    DEPRECATED — не используется. Оставлен как заглушка для обратной совместимости.
    Релевантные файлы и совпадения сохраняются только в PostgreSQL.
    """
    def __init__(self, token: Optional[str], webdav_user: Optional[str], webdav_password: Optional[str], path_template: str, logger, http_client):
        self.yandex_token = None
        self.yandex_webdav_user = webdav_user
        self.yandex_webdav_password = webdav_password
        self.yandex_path_template = path_template
        self.logger = logger
        self.http_client = http_client
        try:
            token_present = False
            webdav_present = bool(self.yandex_webdav_user and self.yandex_webdav_password)
            self.logger.info(f"YandexDisk init: oauth={token_present}, webdav={webdav_present}")
        except Exception:
            pass

    def _ensure_yandex_folder(self, remote_dir: str) -> bool:
        if not remote_dir or remote_dir == "/":
            return True
        if not (self.yandex_webdav_user and self.yandex_webdav_password):
            try:
                self.logger.warning(f"YandexDisk: отсутствуют креды OAuth и WebDAV, создание папки невозможно: {remote_dir}")
            except Exception:
                pass
            return False
        if self.yandex_webdav_user and self.yandex_webdav_password:
            if self._ensure_yandex_folder_webdav(remote_dir):
                return True
        return False

    def _ensure_yandex_folder_oauth(self, remote_dir: str) -> bool:
        url = "https://cloud-api.yandex.net/v1/disk/resources"
        headers = {
            "Authorization": f"OAuth {self.yandex_token}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        proxies = {"http": None, "https": None}
        paths = remote_dir.strip("/").split("/")
        current = ""
        for p in paths:
            current += "/" + p
            for attempt in range(3):
                try:
                    resp = requests.put(url, headers=headers, params={"path": current}, proxies=proxies, timeout=30)
                    if resp.status_code in (201, 409):
                        break
                    else:
                        try:
                            body = ""
                            try:
                                body = resp.text[:300]
                            except Exception:
                                body = ""
                            self.logger.warning(f"Ошибка создания папки {current} (OAuth) {resp.status_code} (попытка {attempt+1}) {body}")
                        except Exception:
                            pass
                except Exception as exc:
                    try:
                        self.logger.warning(f"Исключение создания папки {current} (OAuth): {exc} (попытка {attempt+1})")
                    except Exception:
                        pass
                time.sleep(1)
            else:
                return False
        return True

    def _ensure_yandex_folder_webdav(self, remote_dir: str) -> bool:
        return self._ensure_webdav_dirs(remote_dir)

    def _quote_path(self, path: str) -> str:
        parts = [quote(p) for p in path.split("/")]
        return "/".join(parts)

    def _webdav_url(self, safe_path: str) -> str:
        base = "https://webdav.yandex.ru"
        pt = safe_path if safe_path.startswith("/") else f"/{safe_path}"
        return f"{base}{pt}"

    def _ensure_webdav_dirs(self, remote_dir: str) -> bool:
        paths = [p for p in remote_dir.split("/") if p]
        current = ""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        proxies = {"http": None, "https": None}
        for i, part in enumerate(paths):
            current += "/" + part
            safe_current = self._quote_path(current)
            url = self._webdav_url(safe_current)
            
            exists = False
            for attempt_prop in range(3):
                try:
                    r_prop = requests.request("PROPFIND", url, headers={**headers, "Depth": "0"}, auth=(self.yandex_webdav_user, self.yandex_webdav_password), proxies=proxies, timeout=15)
                    if r_prop.status_code in (200, 207):
                        exists = True
                        break
                    if r_prop.status_code == 404:
                        break
                    try:
                        body = ""
                        try:
                            body = r_prop.text[:300]
                        except Exception:
                            body = ""
                        self.logger.warning(f"WebDAV PROPFIND {url} → {r_prop.status_code} (попытка {attempt_prop+1}) {body}")
                    except Exception:
                        pass
                except Exception as exc:
                    try:
                        self.logger.warning(f"Исключение PROPFIND {url} (попытка {attempt_prop+1}): {exc}")
                    except Exception:
                        pass
                time.sleep(1)
                
            if exists:
                continue

            created = False
            for attempt_mkcol in range(3):
                try:
                    r_mkcol = requests.request("MKCOL", url, headers=headers, auth=(self.yandex_webdav_user, self.yandex_webdav_password), proxies=proxies, timeout=15)
                    if r_mkcol.status_code in (201, 405):
                        created = True
                        break
                    try:
                        body = ""
                        try:
                            body = r_mkcol.text[:300]
                        except Exception:
                            body = ""
                        self.logger.warning(f"WebDAV MKCOL {url} → {r_mkcol.status_code} (попытка {attempt_mkcol+1}) {body}")
                    except Exception:
                        pass
                except Exception as exc:
                    try:
                        self.logger.warning(f"Исключение MKCOL {url} (попытка {attempt_mkcol+1}): {exc}")
                    except Exception:
                        pass
                time.sleep(1)
                
            if not created and not exists:
                try:
                    self.logger.error(f"Не удалось создать директорию WebDAV {url} после 3 попыток")
                except Exception:
                    pass
                return False
        return True

    def _get_yandex_upload_url(self, remote_path: str) -> Optional[str]:
        url = "https://cloud-api.yandex.net/v1/disk/resources/upload"
        headers = {
            "Authorization": f"OAuth {self.yandex_token}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        proxies = {"http": None, "https": None}
        params = {"path": remote_path, "overwrite": "true"}
        try:
            response = requests.get(url, headers=headers, params=params, proxies=proxies, timeout=30)
            if response.ok:
                data = response.json()
                return data.get("href")
        except Exception:
            pass
        return None

    def _file_exists_webdav(self, remote_path: str) -> bool:
        """Проверяет существование файла на Яндекс.Диске через PROPFIND"""
        safe_path = self._quote_path(remote_path)
        url = self._webdav_url(safe_path)
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Depth": "0"
        }
        proxies = {"http": None, "https": None}
        try:
            r = requests.request("PROPFIND", url, headers=headers,
                                 auth=(self.yandex_webdav_user, self.yandex_webdav_password),
                                 proxies=proxies, timeout=15)
            return r.status_code in (200, 207)
        except Exception as e:
            self.logger.warning(f"PROPFIND check failed for {remote_path}: {e}")
            return False

    def _upload_to_yandex_webdav(self, remote_path: str, local_path: Path) -> bool:
        safe_path = self._quote_path(remote_path)
        url = self._webdav_url(safe_path)
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        proxies = {"http": None, "https": None}

        # Если файл уже есть на Яндекс.Диске - не загружаем повторно
        if self._file_exists_webdav(remote_path):
            self.logger.info(f"Файл уже существует на Яндекс.Диске, пропускаем: {remote_path}")
            return True

        file_size = local_path.stat().st_size
        # Timeout: connect 30s, read: min 300s (5 min), or 1s per 10KB (conservative)
        read_timeout = max(300, file_size // 10000)
        
        self.logger.info(f"WebDAV upload start: {local_path.name} -> {url} (size={file_size}, read_timeout={read_timeout})")

        for attempt in range(2):
            try:
                # Use a session to potentially reuse connection
                with requests.Session() as session:
                    with local_path.open("rb") as f:
                        r = session.put(
                            url, 
                            data=f, 
                            auth=(self.yandex_webdav_user, self.yandex_webdav_password), 
                            headers=headers, 
                            proxies=proxies, 
                            timeout=(30, read_timeout)
                        )
                if 200 <= r.status_code < 300:
                    self.logger.info(f"WebDAV upload success: {local_path.name}")
                    return True
                self.logger.warning(f"WebDAV PUT статус {r.status_code} для {url} (попытка {attempt+1}/3). Ответ: {r.text[:200]}")
            except requests.exceptions.Timeout:
                self.logger.warning(f"WebDAV PUT timeout для {url} (попытка {attempt+1}/2)")
            except Exception as e:
                self.logger.warning(f"WebDAV PUT ошибка {e} для {url} (попытка {attempt+1}/2)")
            
            time.sleep(5)  # Wait a bit before retry
            
        self.logger.error(f"Не удалось загрузить файл WebDAV после 2 попыток: {local_path.name}")
        return False

    def build_remote_dir_and_prefix(self, registry_type: Optional[str], contract_number: Optional[str], base_path: Optional[str]) -> tuple[str, str]:
        if not base_path:
            return "", ""

        # Use sanitize_folder_name for directory components to ensure valid folder names (alphanumeric)
        registry_part = self.http_client.sanitize_folder_name(registry_type or "unknown_registry")
        contract_part = self.http_client.sanitize_folder_name(contract_number or "unknown_contract")

        remote_dir = self.yandex_path_template.format(
            base=base_path,
            registry_type=registry_part,
            contract_number=contract_part
        )

        safe_prefix = ""
        if contract_number:
            safe_prefix = f"{self.http_client.sanitize_folder_name(contract_number)}_"

        return remote_dir, safe_prefix

    def upload_file(self, local_path: Path, registry_type: Optional[str], contract_number: Optional[str], base_path: Optional[str]) -> Optional[str]:
        if yandex_disk_disabled():
            self.logger.info("Yandex Disk отключён (DISABLE_YANDEX_DISK=1), upload пропущен")
            return None
        if not base_path:
            self.logger.info("Пропускаю загрузку на Яндекс.Диск: не указан базовый путь")
            return None
        remote_dir, safe_prefix = self.build_remote_dir_and_prefix(registry_type, contract_number, base_path)
        safe_name = self.http_client.sanitize_name(local_path.name)
        # Не добавляем префикс если файл уже содержит номер контракта (rename_file уже добавил)
        if safe_prefix and safe_name.startswith(safe_prefix):
            remote_path = f"{remote_dir}/{safe_name}"
        else:
            remote_path = f"{remote_dir}/{safe_prefix}{safe_name}"
        self.logger.info(f"Сформирован путь загрузки: {remote_path}")

        if not self._ensure_yandex_folder(remote_dir):
            self.logger.error(f"Не удалось создать родительскую папку {remote_dir} (ни OAuth, ни WebDAV), загрузка файла {remote_path} отменена.")
            return None

        if self.yandex_webdav_user and self.yandex_webdav_password:
            self.logger.info(f"Пробую загрузку через WebDAV для {remote_path}")
            ok = self._upload_to_yandex_webdav(remote_path, local_path)
            if ok:
                self.logger.info(f"Загружено на Яндекс.Диск (WebDAV): {remote_path}")
                return remote_path
            else:
                self.logger.warning(f"Ошибка загрузки на Яндекс.Диск (WebDAV): {remote_path}")
                return None

        self.logger.info("Не удалось загрузить файл (все методы исчерпаны)")
        return None

    def upload_matched_file(self, local_path: Path, registry_type: str, contract_number: str) -> Optional[str]:
        if yandex_disk_disabled():
            self.logger.info(
                f"Yandex Disk отключён, файл с совпадениями остаётся локально: {local_path.name}"
            )
            return None
        import os
        base_path = os.getenv("YANDEX_MATCH_BASE_PATH", "Обмен информацией/Отдел продаж/CRM/Лиды/Релевантные")
        # Use sanitize_folder_name for contract folder to match file_enhancer logic
        safe_contract = self.http_client.sanitize_folder_name(contract_number or "unknown")
        remote_dir = f"{base_path}/{safe_contract}"
        safe_name = self.http_client.sanitize_name(local_path.name)
        # Не дублируем префикс если файл уже переименован
        remote_path = f"{remote_dir}/{safe_name}"
        self.logger.info(f"Загрузка релевантного файла: {remote_path}")

        if not self._ensure_yandex_folder(remote_dir):
            self.logger.error(f"Не удалось создать папку {remote_dir}")
            return None

        ok = False
        if self.yandex_webdav_user and self.yandex_webdav_password:
            ok = self._upload_to_yandex_webdav(remote_path, local_path)

        if ok:
            self.logger.info(f"Файл загружен на Яндекс.Диск: {remote_path}")
            try:
                local_path.unlink()
            except OSError:
                pass
            return remote_path
        return None

    def upload_error_file(self, local_path: Path, registry_type: str, contract_number: str, error_message: str) -> Optional[str]:
        if yandex_disk_disabled():
            self.logger.info(
                f"Yandex Disk отключён, upload ошибочного файла пропущен: {local_path.name}"
            )
            return None
        import os
        base_path = os.getenv("YANDEX_ERROR_BASE_PATH", "Обмен информацией/Отдел продаж/CRM/Лиды/Ошибки_парсинга")
        safe_contract = self.http_client.sanitize_name(contract_number or "unknown")
        remote_dir = f"{base_path}/{safe_contract}"
        safe_name = self.http_client.sanitize_name(local_path.name)
        remote_path = f"{remote_dir}/{safe_name}"
        self.logger.info(f"Загрузка ошибочного файла: {remote_path}")

        if not self._ensure_yandex_folder(remote_dir):
            return None

        ok = False
        if self.yandex_webdav_user and self.yandex_webdav_password:
            ok = self._upload_to_yandex_webdav(remote_path, local_path)

        if ok:
            try:
                local_path.unlink()
            except OSError:
                pass
            return remote_path
        return None
