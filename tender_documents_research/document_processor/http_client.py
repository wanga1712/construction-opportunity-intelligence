import os
import re
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests


class HttpFileClient:
    """
    ???????? ?? ?????????? ?????? ?? HTTP/HTTPS (?????? ??????????, ????? ??????, ?????? HTML ????????).
    ????? ???????? ??????? ??? ?????? ? ??????? ??????.
    """
    def __init__(self, proxy_url: Optional[str], proxy_mode: Optional[str], logger):
        self.proxy_url = proxy_url
        self.proxy_mode = proxy_mode
        self.logger = logger
        self.download_start_parallel = max(1, int(os.getenv("DOWNLOAD_START_PARALLEL", "1")))
        self._download_start_gate = threading.BoundedSemaphore(self.download_start_parallel)
        self.session = self._create_download_session()

    def _create_download_session(self) -> requests.Session:
        session = requests.Session()
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util import ssl_

            ssl_context = self._setup_ssl_context()

            class SSLAdapter(HTTPAdapter):
                def init_poolmanager(self, *args, **kwargs):
                    kwargs["ssl_context"] = ssl_context or ssl_.create_urllib3_context()
                    return super(SSLAdapter, self).init_poolmanager(*args, **kwargs)

            adapter = SSLAdapter()
            session.mount("https://", adapter)
        except Exception as e:
            self.logger.warning(f"Could not create SSLAdapter: {e}")
        return session

    def _is_zakupki_download(self, url: str) -> bool:
        return "zakupki.gov.ru" in (url or "")

    def _build_timeout(self, url: str, prefix: str) -> tuple[int, int]:
        if self._is_zakupki_download(url):
            connect_timeout = int(os.getenv(f"{prefix}_CONNECT_TIMEOUT_ZAKUPKI", "75"))
            read_timeout = int(os.getenv(f"{prefix}_READ_TIMEOUT_ZAKUPKI", "300"))
            return connect_timeout, read_timeout
        connect_timeout = int(os.getenv(f"{prefix}_CONNECT_TIMEOUT", "20"))
        read_timeout = int(os.getenv(f"{prefix}_READ_TIMEOUT", "120"))
        return connect_timeout, read_timeout

    def _acquire_download_start(self, url: str) -> bool:
        if not self._is_zakupki_download(url):
            return False
        self.logger.debug(
            f"???????? ????? ?????? ?????????? ??? {url} (limit={self.download_start_parallel})"
        )
        self._download_start_gate.acquire()
        return True

    def _release_download_start(self, acquired: bool) -> None:
        if acquired:
            self._download_start_gate.release()

    def try_download_direct(self, task_dir: Path, url: str, suggested_filename: Optional[str] = None) -> Optional[Path]:
        """?????? ??????????: ???????????????? ?????, ????? ???????????? ???????? ????."""
        start_acquired = False
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0"
            }
            if "zakupki.gov.ru" in url:
                headers["Referer"] = "https://zakupki.gov.ru/"
            self.logger.debug(f"?????? ??????????: {url}")

            timeout_tuple = self._build_timeout(url, "DIRECT")
            verify = self._get_verify_param()
            start_acquired = self._acquire_download_start(url)
            response = self.session.get(
                url,
                headers=headers,
                timeout=timeout_tuple,
                stream=True,
                verify=verify,
            )
            self._release_download_start(start_acquired)
            start_acquired = False

            with response:
                if not response.ok:
                    self.logger.warning(f"?????? ?????? ?????? ??? {response.status_code}")
                    return None

                ct = (response.headers.get("Content-Type") or "").lower()
                url_path = url.split("?", 1)[0].lower()
                if "text/html" in ct and not url_path.endswith(".html"):
                    cl_header = response.headers.get("Content-Length")
                    if cl_header is not None and int(cl_header) < 50000:
                        self.logger.warning(
                            f"????????, ????????? ???????? ?????? ????? (Content-Type: {ct}, Content-Length: {cl_header})"
                        )
                        return None

                filename = self.sanitize_name(suggested_filename) if suggested_filename else self._resolve_filename(url, response.headers)
                local_path = task_dir / filename
                with local_path.open("wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            return local_path
        except Exception as e:
            self.logger.warning(f"?????? ??????? ??????????: {e}")
            return None
        finally:
            self._release_download_start(start_acquired)

    def try_download_with_proxy(self, task_dir: Path, url: str, suggested_filename: Optional[str] = None) -> Optional[Path]:
        if not self.proxy_url:
            return None
        start_acquired = False
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            host = self.extract_host(url)
            if host:
                headers["Host"] = host
            mode = (self.proxy_mode or "endpoint").lower()
            verify = self._get_verify_param()
            timeout_tuple = self._build_timeout(url, "PROXY")
            if mode in ("http", "proxy", "http_proxy"):
                self.logger.debug(f"?????????? ????? HTTP-??????: {self.proxy_url}")
                proxies = {"http": self.proxy_url, "https": self.proxy_url}
                start_acquired = self._acquire_download_start(url)
                response = self.session.get(url, headers=headers, timeout=timeout_tuple, stream=True, proxies=proxies, verify=verify)
                self._release_download_start(start_acquired)
                start_acquired = False
                with response:
                    if not response.ok:
                        self.logger.warning(f"HTTP-?????? ?????: {response.status_code}")
                        return None
                    filename = self.sanitize_name(suggested_filename) if suggested_filename else self._resolve_filename(url, response.headers)
                    local_path = task_dir / filename
                    with local_path.open("wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                return local_path
            elif mode in ("reverse", "revproxy", "reverse_proxy"):
                parts = urlsplit(url)
                path_and_query = parts.path or "/"
                if parts.query:
                    path_and_query = f"{path_and_query}?{parts.query}"
                target = f"{self.proxy_url.rstrip('/')}{path_and_query}"
                self.logger.debug(f"?????????? ????? reverse-??????: {target}")
                start_acquired = self._acquire_download_start(url)
                response = self.session.get(target, headers=headers, timeout=timeout_tuple, stream=True, verify=verify)
                self._release_download_start(start_acquired)
                start_acquired = False
                with response:
                    if not response.ok:
                        self.logger.warning(f"Reverse-?????? ?????: {response.status_code}")
                        return None
                    filename = self._resolve_filename(url, response.headers)
                    local_path = task_dir / filename
                    with local_path.open("wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                return local_path
            else:
                self.logger.debug(f"?????????? ????? endpoint-??????: {self.proxy_url}")
                start_acquired = self._acquire_download_start(url)
                response = self.session.get(self.proxy_url, params={"url": url}, headers=headers, timeout=timeout_tuple, stream=True, verify=verify)
                self._release_download_start(start_acquired)
                start_acquired = False
                with response:
                    if not response.ok:
                        self.logger.warning(f"Endpoint-?????? ?????: {response.status_code}")
                        return None
                    filename = self._resolve_filename(url, response.headers)
                    local_path = task_dir / filename
                    with local_path.open("wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                return local_path
        except Exception:
            return None
        finally:
            self._release_download_start(start_acquired)

    def download_html_and_follow(self, task_dir: Path, page_url: str) -> Optional[Path]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate, br",
            }
            self.logger.debug(f"Загрузка HTML страницы: {page_url}")
            verify = self._get_verify_param()
            with self.session.get(page_url, headers=headers, timeout=60, verify=verify) as resp:
                if not resp.ok:
                    self.logger.warning(f"HTML страница недоступна: {resp.status_code}")
                    return None
                html = resp.text or ""
        except Exception:
            return None

        candidates: list[str] = []
        try:
            for m in re.finditer(r'href=["\\\'](?P<h>[^"\\\']+)["\\\']', html, flags=re.IGNORECASE):
                href = m.group("h")
                if not href:
                    continue
                low = href.lower()
                if any(s in low for s in ("/filestore/public/1.0/download/", "/filestore/", "/download/")) and not low.endswith(".html"):
                    candidates.append(urljoin(page_url, href))
            if not candidates:
                for m in re.finditer(r'href=["\\\'](?P<h>[^"\\\']+)["\\\']', html, flags=re.IGNORECASE):
                    href = m.group("h")
                    if not href:
                        continue
                    low = href.lower()
                    if any(low.endswith(ext) for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")):
                        candidates.append(urljoin(page_url, href))
        except Exception:
            candidates = []

        if not candidates:
            self.logger.debug("Не найдено ссылок на вложения в HTML")
            return None

        for cand in candidates[:5]:
            self.logger.debug(f"Пробую вложение: {cand}")
            host = self.extract_host(cand) or ""
            if "zakupki.gov.ru" in host and "/filestore/public/1.0/download/" in cand:
                path = self.try_download_with_proxy(task_dir, cand)
                if path: return path
            path = self.try_download_direct(task_dir, cand)
            if path: return path
            path = self.try_download_with_proxy(task_dir, cand)
            if path: return path
        return None

    def is_proxy_alive(self) -> bool:
        """Проверяет доступен ли прокси-сервер."""
        if not self.proxy_url:
            return True
        try:
            from urllib.parse import urlparse
            import socket
            parsed = urlparse(self.proxy_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8080
            with socket.create_connection((host, port), timeout=3):
                return True
        except Exception as e:
            self.logger.warning(f"Proxy check failed: {e}")
            return False

    def extract_host(self, url: str) -> Optional[str]:
        try:
            without_scheme = url.split("://", 1)[1]
            host_port = without_scheme.split("/", 1)[0]
            return host_port
        except Exception:
            return None

    def _resolve_filename(self, url: str, headers: dict) -> str:
        cd = headers.get("Content-Disposition") or headers.get("content-disposition")
        if cd:
            lower = cd.lower()
            if "filename*=" in lower:
                try:
                    val = cd.split("filename*=", 1)[1].split(";", 1)[0].strip().strip('"').strip("'")
                    if val.lower().startswith("utf-8''"):
                        val = val[7:]
                    name = unquote(val)
                    if name and not self._looks_mojibake(name):
                        return name
                except Exception:
                    pass
            parts = cd.split(";")
            for p in parts:
                p = p.strip()
                if p.lower().startswith("filename="):
                    name = p.split("=", 1)[1].strip().strip('\"')
                    if name:
                        if not self._looks_mojibake(name):
                            return name
                        base_ext = os.path.splitext(name)[1]
                        if base_ext:
                            uid = self._extract_uid(url) or ""
                            return f"file_{uid}{base_ext}" if uid else f"file{base_ext}"
        ct = headers.get("Content-Type") or headers.get("content-type") or ""
        ext = ""
        if "application/pdf" in ct:
            ext = ".pdf"
        elif "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in ct:
            ext = ".docx"
        elif "application/msword" in ct:
            ext = ".doc"
        elif "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in ct:
            ext = ".xlsx"
        elif "text/html" in ct:
            ext = ".html"
        tail = url.split("/")[-1] or "file"
        if "?" in tail:
            tail = tail.split("?", 1)[0]
        if not tail:
            tail = "file"
        if ext and not tail.endswith(ext):
            tail = tail + ext
        if self._looks_mojibake(tail):
            uid = self._extract_uid(url) or ""
            base = f"file_{uid}" if uid else "file"
            tail = base + ext if ext else base
        return tail

    def _looks_mojibake(self, s: str) -> bool:
        bad = ["Ð", "Ñ", "\ufffd"]
        return any(ch in s for ch in bad)

    def _extract_uid(self, url: str) -> Optional[str]:
        try:
            qs = urlsplit(url).query
            params = parse_qs(qs)
            v = params.get("uid")
            if v and v[0]:
                return v[0]
        except Exception:
            return None
        return None

    def predict_filename(self, url: str) -> str:
        tail = url.split("/")[-1] or "file"
        if "?" in tail:
            tail = tail.split("?", 1)[0]
        if not tail:
            tail = "file"
        return tail

    def sanitize_name(self, name: str) -> str:
        """
        Очистка имени файла (допускает точки, подчеркивания, но убирает спецсимволы).
        Используется для файлов.
        """
        if not name:
            return "unknown_file"

        # 1. Заменяем стандартные запрещенные символы и расширенный набор спецсимволов
        forbidden_chars = [
            "/", "\\", ":", "*", "?", "<", ">", "|", '"',
            "+", "%", "#", "&", "{", "}", "[", "]", "=", ";", ",", "'", "@", "!", "$", "`", "^"
        ]

        cleaned = name
        for char in forbidden_chars:
            cleaned = cleaned.replace(char, "_")

        # 2. Убираем управляющие символы (0-31)
        cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32)

        # 3. Убираем скобки и тильды (по запросу пользователя)
        cleaned = cleaned.replace("(", "_").replace(")", "_").replace("~", "_")

        # 4. Убираем двойные подчеркивания
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")

        cleaned = cleaned.strip(" ._")

        if not cleaned:
            return "unknown_file"

        # 5. Ограничиваем длину
        if len(cleaned) > 200:
            base, ext = os.path.splitext(cleaned)
            if len(ext) > 10:
                ext = ""
            limit = 200 - len(ext)
            cleaned = base[:limit] + ext

        return cleaned

    def sanitize_folder_name(self, name: str) -> str:
        """
        Строгая очистка для имен папок (контрактов/реестров).
        Оставляет ТОЛЬКО буквы и цифры.
        Совместимо с логикой file_enhancer._sanitize_contract.
        """
        if not name:
            return "unknown"
        return "".join(ch for ch in str(name) if ch.isalnum())

    def _setup_ssl_context(self):
        """Настройка SSL контекста с пользовательскими сертификатами"""
        from urllib3.util.ssl_ import create_urllib3_context

        ctx = create_urllib3_context()
        try:
            ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        except:
            pass

        ctx.check_hostname = False

        # Загружаем пользовательский сертификат
        cert_path = os.getenv('CLIENT_CERT_PATH')
        key_path = os.getenv('CLIENT_KEY_PATH')

        if not cert_path:
            # Ищем в стандартных местах
            possible_paths = [
                '/etc/stunnel/client.pem',
                '/opt/tendermonitor/certs/client.pem',
                '/home/tender/certs/client.pem'
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    cert_path = path
                    break

        if cert_path and os.path.exists(cert_path):
            try:
                if key_path and os.path.exists(key_path):
                    ctx.load_cert_chain(cert_path, key_path)
                else:
                    ctx.load_cert_chain(cert_path)
                self.logger.info(f"Загружен пользовательский сертификат: {cert_path}")
            except Exception as e:
                self.logger.warning(f"Не удалось загрузить сертификат: {e}")

        return ctx

    def _get_verify_param(self):
        ca_bundle = os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("CURL_CA_BUNDLE")
        if ca_bundle and os.path.exists(ca_bundle):
            return ca_bundle
        return os.getenv("REQUESTS_VERIFY_SSL", "0") == "1"
