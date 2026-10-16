"""UNSUPPORTED_DOC_RECOVERY_V1 — конвертация неподдерживаемых форматов.

Пайплайн понимает `.xlsx/.xlsm/.docx/.pdf` (и `.doc` через antiword). Старые
форматы `.xls` (BIFF) и `.rtf` парсеров не имеют, из-за чего строки очереди
падали в `LOCAL_CLASSIFIED:*:UNSUPPORTED`.

Штатный путь (задокументирован в `docs/wip/WIP_UNSUPPORTED_DOC_RECOVERY_V1.md`):
скачать нужный документ **вне очереди** → сконвертировать через `soffice`
(`.xls → .xlsx`, `.rtf → .docx`) → разобрать **вне очереди** по категории
закупки. Здесь — только шаг конвертации; новых зависимостей не требуется
(`soffice`/`libreoffice` уже стоят на S13).

Конвертация best-effort: при отсутствии `soffice` или ошибке возвращается
исходный путь (поведение как раньше — UNSUPPORTED).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

#: исходный формат -> целевой (понимаемый парсерами)
CONVERTIBLE = {
    ".xls": "xlsx",
    ".rtf": "docx",
}
_SOFFICE_CANDIDATES = ("soffice", "libreoffice")
DEFAULT_CACHE_DIR = "/tmp/tender-doc-converted"

#: Suffixes our parsers read directly; content sniffing is skipped for them.
_NATIVE_SUFFIXES = frozenset({".xlsx", ".xlsm", ".docx", ".pdf"})


def soffice_binary() -> Optional[str]:
    for name in _SOFFICE_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def is_convertible(path: Path) -> bool:
    return Path(path).suffix.lower() in CONVERTIBLE


def sniff_ooxml_kind(path: Path) -> Optional[str]:
    """UNSUPPORTED_DOC_RECOVERY_V1: detect a mislabeled OOXML package.

    EIS occasionally serves a ZIP-based OOXML document (.xlsx/.docx) under a
    foreign name (e.g. `.rtf`). Returns the real extension without the dot
    ("xlsx"/"docx") when the payload is an OOXML package, else None.
    """
    try:
        if not zipfile.is_zipfile(str(path)):
            return None
        with zipfile.ZipFile(str(path)) as zf:
            names = set(zf.namelist())
    except Exception:
        return None
    if "[Content_Types].xml" not in names:
        return None
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    if any(n.startswith("word/") for n in names):
        return "docx"
    return None


def _materialize_as(path: Path, target_ext: str, cache_dir: str) -> Optional[Path]:
    """Cache a re-labelled copy of `path` with `target_ext` (content unchanged)."""
    try:
        cached = _cache_path(path, target_ext, cache_dir)
        if cached.is_file() and cached.stat().st_size > 0:
            return cached
        os.makedirs(cache_dir, exist_ok=True)
        shutil.copyfile(str(path), str(cached))
        return cached if cached.stat().st_size > 0 else None
    except Exception:
        return None


def _cache_path(path: Path, target_ext: str, cache_dir: str) -> Path:
    st = None
    try:
        st = os.stat(path)
    except OSError:
        pass
    key = "|".join([
        str(path), str(st.st_size if st else ""), str(int(st.st_mtime) if st else ""),
    ])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return Path(cache_dir) / f"{Path(path).stem[:60]}.{digest}.{target_ext}"


def convert_if_needed(path: Path, *, cache_dir: str = DEFAULT_CACHE_DIR,
                      timeout: int = 120) -> Path:
    """Вернуть путь к разбираемому файлу: исходный или сконвертированный.

    `.xls → .xlsx`, `.rtf → .docx` через headless `soffice`. Результат кэшируется;
    при любой ошибке возвращается исходный путь (fail-soft).
    """
    src = Path(path)
    target_ext = CONVERTIBLE.get(src.suffix.lower())
    if not src.is_file():
        return src
    # A mislabeled OOXML package needs no soffice round-trip: re-label it.
    if src.suffix.lower() not in _NATIVE_SUFFIXES:
        kind = sniff_ooxml_kind(src)
        if kind:
            materialized = _materialize_as(src, kind, cache_dir)
            if materialized is not None:
                return materialized
    if not target_ext:
        return src
    binary = soffice_binary()
    if not binary:
        return src
    cached = _cache_path(src, target_ext, cache_dir)
    if cached.is_file() and cached.stat().st_size > 0:
        return cached
    try:
        os.makedirs(cache_dir, exist_ok=True)
        tmp_dir = cached.parent / f"{cached.stem}.out"
        os.makedirs(tmp_dir, exist_ok=True)
        subprocess.run(
            [binary, "--headless", "--norestore", "--convert-to", target_ext,
             "--outdir", str(tmp_dir), str(src)],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=timeout,
        )
        produced = tmp_dir / f"{src.stem}.{target_ext}"
        if produced.is_file() and produced.stat().st_size > 0:
            shutil.move(str(produced), str(cached))
            return cached
    except Exception:
        return src
    return src
