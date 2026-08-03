"""Скачивание документации закупки и упаковка в один ZIP."""
from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Dict, List, Tuple

from loguru import logger

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

import urllib.request

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT_SEC = 180


def _safe_zip_name(name: str, used: set[str]) -> str:
    base = (name or "document").strip() or "document"
    base = re.sub(r'[<>:"/\\|?*]', "_", base)
    candidate = base
    n = 2
    while candidate in used:
        stem, dot, ext = base.rpartition(".")
        if dot:
            candidate = f"{stem}_{n}.{ext}"
        else:
            candidate = f"{base}_{n}"
        n += 1
    used.add(candidate)
    return candidate


def _fetch_url(url: str) -> bytes:
    if requests is not None:
        resp = requests.get(
            url,
            timeout=_TIMEOUT_SEC,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.content

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        return resp.read()


def bundle_filename(contract_number: str | None, tender_id: int | None) -> str:
    stem = (contract_number or "").strip() or (str(tender_id) if tender_id else "tender")
    stem = re.sub(r'[<>:"/\\|?*]', "_", stem)
    return f"{stem}_documentation.zip"


def build_documents_zip(
    documents: List[Dict[str, Any]],
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Скачать все документы с площадки и упаковать в один ZIP в памяти.
    """
    buffer = io.BytesIO()
    used_names: set[str] = set()
    ok = 0
    failed: List[str] = []

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, doc in enumerate(documents, 1):
            url = (doc.get("url") or "").strip()
            name = (doc.get("file_name") or f"document_{doc.get('doc_id', idx)}").strip()
            if not url:
                failed.append(f"{name} (нет ссылки)")
                continue
            zip_name = _safe_zip_name(name, used_names)
            try:
                logger.info(f"ZIP bundle: [{idx}/{len(documents)}] {name}")
                data = _fetch_url(url)
                if not data:
                    failed.append(f"{name} (пустой файл)")
                    continue
                zf.writestr(zip_name, data)
                ok += 1
            except Exception as exc:
                logger.warning(f"ZIP bundle failed for {name}: {exc}")
                failed.append(f"{name}")

    buffer.seek(0)
    stats = {
        "ok": ok,
        "total": len(documents),
        "failed": failed,
        "size_bytes": buffer.getbuffer().nbytes,
    }
    return buffer.getvalue(), stats


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} Б"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} КБ"
    return f"{num_bytes / (1024 * 1024):.1f} МБ"
