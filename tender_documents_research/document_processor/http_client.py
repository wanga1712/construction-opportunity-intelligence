import os
import re
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests

from .concurrency_manager import get_current_eis_concurrency
from .eis_rate_limit_guard import (
    EisRateLimitBlocked,
    EisRateLimited,
    extract_xid,
    get_eis_guard,
    is_eis_url,
    parse_retry_after,
)


class HttpFileClient:
    """HTTP download client. Every EIS request passes the same global gate."""

    def __init__(
        self,
        proxy_url: Optional[str],
        proxy_mode: Optional[str],
        logger,
        guard=None,
    ):
        self.proxy_url = proxy_url
        self.proxy_mode = proxy_mode
        self.logger = logger
        self.guard = guard or get_eis_guard()
        self.download_start_parallel = max(
            1, int(os.getenv("DOWNLOAD_START_PARALLEL", "1"))
        )
        self._download_start_gate = threading.BoundedSemaphore(
            self.download_start_parallel
        )
        self._request_gate: Callable[[str], Any] = (
            lambda request_type: nullcontext()
        )
        self.session = self._create_download_session()

    def set_request_gate(self, request_gate: Callable[[str], Any]) -> None:
        self._request_gate = request_gate

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
        except Exception as exc:
            self.logger.warning(f"Could not create SSLAdapter: {exc}")
        return session

    def _is_zakupki_download(self, url: str) -> bool:
        return is_eis_url(url)

    def _build_timeout(self, url: str, prefix: str) -> tuple[int, int]:
        if self._is_zakupki_download(url):
            connect_timeout = int(
                os.getenv(f"{prefix}_CONNECT_TIMEOUT_ZAKUPKI", "75")
            )
            read_timeout = int(os.getenv(f"{prefix}_READ_TIMEOUT_ZAKUPKI", "300"))
            return connect_timeout, read_timeout
        connect_timeout = int(os.getenv(f"{prefix}_CONNECT_TIMEOUT", "20"))
        read_timeout = int(os.getenv(f"{prefix}_READ_TIMEOUT", "120"))
        return connect_timeout, read_timeout

    def _acquire_download_start(self, url: str) -> bool:
        if not self._is_zakupki_download(url):
            return False
        self._download_start_gate.acquire()
        return True

    def _release_download_start(self, acquired: bool) -> None:
        if acquired:
            self._download_start_gate.release()

    def _request(
        self,
        method: str,
        url: str,
        *,
        request_type: str = "DOWNLOAD",
        eis_url: Optional[str] = None,
        **kwargs,
    ):
        """Execute one HTTP request; 429 raises immediately without retry."""
        guarded_url = eis_url or url
        if not self._is_zakupki_download(guarded_url):
            return self.session.request(method, url, **kwargs)

        event_id = 0
        started = time.monotonic()
        start_acquired = False
        with self._request_gate(request_type):
            self.guard.ensure_request_allowed(request_type)
            event_id = self.guard.record_request_start(
                request_type,
                guarded_url,
                get_current_eis_concurrency(),
            )
            try:
                start_acquired = self._acquire_download_start(guarded_url)
                response = self.session.request(method, url, **kwargs)
            except Exception as exc:
                self.guard.record_request_finish(
                    event_id,
                    None,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error_class=type(exc).__name__,
                )
                raise
            finally:
                self._release_download_start(start_acquired)

        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            try:
                body_sample = (response.text or "")[:4096]
            except Exception:
                body_sample = ""
            xid = extract_xid(body_sample)
            response_headers = dict(response.headers)
            self.guard.record_request_finish(
                event_id,
                429,
                duration_ms=duration_ms,
                xid=xid,
                retry_after=retry_after,
            )
            self.guard.record_429(
                guarded_url,
                retry_after,
                xid,
                get_current_eis_concurrency(),
            )
            response.close()
            raise EisRateLimited(
                guarded_url, retry_after, xid, response_headers
            )
        self.guard.record_request_finish(
            event_id,
            response.status_code,
            duration_ms=duration_ms,
        )
        return response

    def request_head(self, url: str, request_type: str = "HEAD", **kwargs):
        return self._request("HEAD", url, request_type=request_type, **kwargs)

    def _write_response(self, task_dir: Path, url: str, response, suggested_filename=None) -> Path:
        filename = (
            self.sanitize_name(suggested_filename)
            if suggested_filename
            else self._resolve_filename(url, response.headers)
        )
        local_path = task_dir / filename
        with local_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
        return local_path

    def try_download_direct(
        self,
        task_dir: Path,
        url: str,
        suggested_filename: Optional[str] = None,
        request_type: str = "DOWNLOAD",
    ) -> Optional[Path]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        if is_eis_url(url):
            headers["Referer"] = "https://zakupki.gov.ru/"
        try:
            response = self._request(
                "GET",
                url,
                request_type=request_type,
                headers=headers,
                timeout=self._build_timeout(url, "DIRECT"),
                stream=True,
                verify=self._get_verify_param(),
            )
            with response:
                if not response.ok:
                    self.logger.warning(
                        f"Direct download failed with {response.status_code}"
                    )
                    return None
                content_type = (response.headers.get("Content-Type") or "").lower()
                url_path = url.split("?", 1)[0].lower()
                if "text/html" in content_type and not url_path.endswith(".html"):
                    length = response.headers.get("Content-Length")
                    if length is not None and int(length) < 50000:
                        self.logger.warning(
                            "Rejected small HTML response: "
                            f"{content_type}, length={length}"
                        )
                        return None
                return self._write_response(
                    task_dir, url, response, suggested_filename
                )
        except (EisRateLimited, EisRateLimitBlocked):
            raise
        except Exception as exc:
            self.logger.warning(f"Direct download failed: {exc}")
            return None

    def try_download_with_proxy(
        self,
        task_dir: Path,
        url: str,
        suggested_filename: Optional[str] = None,
        request_type: str = "DOWNLOAD",
    ) -> Optional[Path]:
        if not self.proxy_url:
            return None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        host = self.extract_host(url)
        if host:
            headers["Host"] = host
        mode = (self.proxy_mode or "endpoint").lower()
        verify = self._get_verify_param()
        timeout_tuple = self._build_timeout(url, "PROXY")
        try:
            if mode in ("http", "proxy", "http_proxy"):
                proxies = {"http": self.proxy_url, "https": self.proxy_url}
                response = self._request(
                    "GET",
                    url,
                    request_type=request_type,
                    eis_url=url,
                    headers=headers,
                    timeout=timeout_tuple,
                    stream=True,
                    proxies=proxies,
                    verify=verify,
                )
            elif mode in ("reverse", "revproxy", "reverse_proxy"):
                parts = urlsplit(url)
                path_and_query = parts.path or "/"
                if parts.query:
                    path_and_query = f"{path_and_query}?{parts.query}"
                target = f"{self.proxy_url.rstrip('/')}{path_and_query}"
                response = self._request(
                    "GET",
                    target,
                    request_type=request_type,
                    eis_url=url,
                    headers=headers,
                    timeout=timeout_tuple,
                    stream=True,
                    verify=verify,
                )
            else:
                response = self._request(
                    "GET",
                    self.proxy_url,
                    request_type=request_type,
                    eis_url=url,
                    params={"url": url},
                    headers=headers,
                    timeout=timeout_tuple,
                    stream=True,
                    verify=verify,
                )
            with response:
                if not response.ok:
                    self.logger.warning(
                        f"Proxy download failed with {response.status_code}"
                    )
                    return None
                return self._write_response(
                    task_dir, url, response, suggested_filename
                )
        except (EisRateLimited, EisRateLimitBlocked):
            raise
        except Exception as exc:
            self.logger.warning(f"Proxy download failed: {exc}")
            return None

    def download_html_and_follow(self, task_dir: Path, page_url: str) -> Optional[Path]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
        }
        try:
            with self._request(
                "GET",
                page_url,
                request_type="HTML",
                headers=headers,
                timeout=60,
                verify=self._get_verify_param(),
            ) as response:
                if not response.ok:
                    self.logger.warning(
                        f"HTML page unavailable: {response.status_code}"
                    )
                    return None
                html = response.text or ""
        except (EisRateLimited, EisRateLimitBlocked):
            raise
        except Exception:
            return None

        candidates: list[str] = []
        try:
            for match in re.finditer(
                r'href=["\\\'](?P<h>[^"\\\']+)["\\\']', html, flags=re.IGNORECASE
            ):
                href = match.group("h")
                low = href.lower()
                if any(
                    token in low
                    for token in (
                        "/filestore/public/1.0/download/",
                        "/filestore/",
                        "/download/",
                    )
                ) and not low.endswith(".html"):
                    candidates.append(urljoin(page_url, href))
            if not candidates:
                for match in re.finditer(
                    r'href=["\\\'](?P<h>[^"\\\']+)["\\\']',
                    html,
                    flags=re.IGNORECASE,
                ):
                    href = match.group("h")
                    low = href.lower()
                    if any(
                        low.endswith(ext)
                        for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")
                    ):
                        candidates.append(urljoin(page_url, href))
        except Exception:
            candidates = []

        if not candidates:
            return None
        for candidate in candidates[:5]:
            host = self.extract_host(candidate) or ""
            if "zakupki.gov.ru" in host and "/filestore/public/1.0/download/" in candidate:
                path = self.try_download_with_proxy(task_dir, candidate)
                if path:
                    return path
            path = self.try_download_direct(task_dir, candidate)
            if path:
                return path
            path = self.try_download_with_proxy(task_dir, candidate)
            if path:
                return path
        return None

    def is_proxy_alive(self) -> bool:
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
        except Exception as exc:
            self.logger.warning(f"Proxy check failed: {exc}")
            return False

    def extract_host(self, url: str) -> Optional[str]:
        try:
            without_scheme = url.split("://", 1)[1]
            return without_scheme.split("/", 1)[0]
        except Exception:
            return None

    def _resolve_filename(self, url: str, headers: dict) -> str:
        content_disposition = headers.get("Content-Disposition") or headers.get(
            "content-disposition"
        )
        if content_disposition:
            lower = content_disposition.lower()
            if "filename*=" in lower:
                try:
                    value = (
                        content_disposition.split("filename*=", 1)[1]
                        .split(";", 1)[0]
                        .strip()
                        .strip('"')
                        .strip("'")
                    )
                    if value.lower().startswith("utf-8''"):
                        value = value[7:]
                    name = unquote(value)
                    if name and not self._looks_mojibake(name):
                        return name
                except Exception:
                    pass
            for part in content_disposition.split(";"):
                part = part.strip()
                if part.lower().startswith("filename="):
                    name = part.split("=", 1)[1].strip().strip('"')
                    if name:
                        if not self._looks_mojibake(name):
                            return name
                        extension = os.path.splitext(name)[1]
                        if extension:
                            uid = self._extract_uid(url) or ""
                            return f"file_{uid}{extension}" if uid else f"file{extension}"
        content_type = (
            headers.get("Content-Type") or headers.get("content-type") or ""
        )
        extension = ""
        if "application/pdf" in content_type:
            extension = ".pdf"
        elif (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            in content_type
        ):
            extension = ".docx"
        elif "application/msword" in content_type:
            extension = ".doc"
        elif (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            in content_type
        ):
            extension = ".xlsx"
        elif "text/html" in content_type:
            extension = ".html"
        tail = url.split("/")[-1] or "file"
        if "?" in tail:
            tail = tail.split("?", 1)[0]
        if not tail:
            tail = "file"
        if extension and not tail.endswith(extension):
            tail = tail + extension
        if self._looks_mojibake(tail):
            uid = self._extract_uid(url) or ""
            base = f"file_{uid}" if uid else "file"
            tail = base + extension if extension else base
        return tail

    def _looks_mojibake(self, value: str) -> bool:
        return any(ch in value for ch in ["Гђ", "Г‘", "\ufffd"])

    def _extract_uid(self, url: str) -> Optional[str]:
        try:
            params = parse_qs(urlsplit(url).query)
            value = params.get("uid")
            return value[0] if value and value[0] else None
        except Exception:
            return None

    def predict_filename(self, url: str) -> str:
        tail = url.split("/")[-1] or "file"
        if "?" in tail:
            tail = tail.split("?", 1)[0]
        return tail or "file"

    def sanitize_name(self, name: str) -> str:
        if not name:
            return "unknown_file"
        forbidden = [
            "/", "\\", ":", "*", "?", "<", ">", "|", '"',
            "+", "%", "#", "&", "{", "}", "[", "]", "=", ";", ",", "'",
            "@", "!", "$", "`", "^",
        ]
        cleaned = name
        for char in forbidden:
            cleaned = cleaned.replace(char, "_")
        cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32)
        cleaned = cleaned.replace("(", "_").replace(")", "_").replace("~", "_")
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        cleaned = cleaned.strip(" ._")
        if not cleaned:
            return "unknown_file"
        if len(cleaned) > 200:
            base, extension = os.path.splitext(cleaned)
            if len(extension) > 10:
                extension = ""
            cleaned = base[: 200 - len(extension)] + extension
        return cleaned

    def sanitize_folder_name(self, name: str) -> str:
        if not name:
            return "unknown"
        return "".join(ch for ch in str(name) if ch.isalnum())

    def _setup_ssl_context(self):
        from urllib3.util.ssl_ import create_urllib3_context

        context = create_urllib3_context()
        try:
            context.set_ciphers("DEFAULT:@SECLEVEL=1")
        except Exception:
            pass
        context.check_hostname = False

        cert_path = os.getenv("CLIENT_CERT_PATH")
        key_path = os.getenv("CLIENT_KEY_PATH")
        if not cert_path:
            for path in (
                "/etc/stunnel/client.pem",
                "/opt/tendermonitor/certs/client.pem",
                "/home/tender/certs/client.pem",
            ):
                if os.path.exists(path):
                    cert_path = path
                    break
        if cert_path and os.path.exists(cert_path):
            try:
                if key_path and os.path.exists(key_path):
                    context.load_cert_chain(cert_path, key_path)
                else:
                    context.load_cert_chain(cert_path)
                self.logger.info(f"Loaded client certificate: {cert_path}")
            except Exception as exc:
                self.logger.warning(f"Could not load client certificate: {exc}")
        return context

    def _get_verify_param(self):
        bundle = os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("CURL_CA_BUNDLE")
        if bundle and os.path.exists(bundle):
            return bundle
        return os.getenv("REQUESTS_VERIFY_SSL", "0") == "1"
