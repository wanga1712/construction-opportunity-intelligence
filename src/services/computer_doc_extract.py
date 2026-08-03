"""Extract text from computer tender docs using tender_documents_research parsers.

Reuses PdfParser / WordParser / DocParser / ExcelParser from the materials daemon
stack so computers contour stays parallel but shares the same file engines.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from loguru import logger

_RESEARCH_ROOT_CANDIDATES = (
    os.environ.get("TENDER_DOCS_RESEARCH_ROOT", "").strip(),
    "/opt/tender_documents_research",
    str(Path(__file__).resolve().parents[3] / "tender_documents_research"),
    str(Path(__file__).resolve().parents[2].parent / "tender_documents_research"),
)

_SUPPORTED = {".pdf", ".docx", ".doc", ".xlsx", ".xlsm", ".odt", ".txt", ".csv"}
_ARCHIVE = {".zip"}


def _ensure_research_on_path() -> Optional[Path]:
    import sys

    for raw in _RESEARCH_ROOT_CANDIDATES:
        if not raw:
            continue
        root = Path(raw)
        if (root / "document_processor" / "parser_factory.py").is_file():
            s = str(root.resolve())
            if s not in sys.path:
                sys.path.insert(0, s)
            return root
    return None


def extract_text_from_file(path: Path) -> str:
    """Parse a single file with the research ParserFactory."""
    research = _ensure_research_on_path()
    if research is None:
        logger.warning("tender_documents_research not found — cannot use shared parsers")
        return ""

    suffix = path.suffix.lower()
    if suffix in _ARCHIVE:
        return _extract_archive(path)

    try:
        from document_processor.parser_factory import ParserFactory
        from document_processor.parse_utils import parse_file_with_meta
    except Exception as exc:
        logger.warning(f"import research parsers failed: {exc}")
        return ""

    factory = ParserFactory()
    parser = factory.get_parser(path)
    if parser is None:
        logger.debug(f"no parser for {path.name}")
        return ""
    try:
        text, _meta = parse_file_with_meta(parser, path)
        return (text or "").strip()
    except Exception as exc:
        logger.warning(f"parse failed {path.name}: {exc}")
        return ""


def _extract_archive(archive_path: Path) -> str:
    parts: List[str] = []
    with tempfile.TemporaryDirectory(prefix="crm_comp_zip_") as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(tmp_path)
        except Exception as exc:
            logger.warning(f"zip extract failed {archive_path.name}: {exc}")
            return ""
        for child in sorted(tmp_path.rglob("*")):
            if not child.is_file():
                continue
            if child.suffix.lower() not in _SUPPORTED:
                continue
            text = extract_text_from_file(child)
            if text:
                parts.append(f"=== {child.name} ===\n{text}")
    return "\n\n".join(parts)


def extract_text_from_bytes(data: bytes, filename: str) -> str:
    """Write bytes to a temp file and parse with shared engines."""
    name = (filename or "document.bin").replace("/", "_").replace("\\", "_")
    suffix = Path(name).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="crm_comp_doc_") as tmp:
        path = Path(tmp) / name
        path.write_bytes(data)
        # Some CDNs serve zip without .zip extension
        if suffix not in _SUPPORTED | _ARCHIVE and data[:2] == b"PK":
            renamed = path.with_suffix(".zip")
            path.rename(renamed)
            path = renamed
        return extract_text_from_file(path)


def combine_document_texts(chunks: Iterable[Tuple[str, str]], *, max_chars: int = 60000) -> str:
    """Merge (filename, text) chunks with a hard size cap for the model."""
    parts: List[str] = []
    total = 0
    for name, text in chunks:
        block = f"=== {name} ===\n{(text or '').strip()}"
        if not (text or "").strip():
            continue
        if total + len(block) > max_chars:
            remain = max_chars - total
            if remain > 500:
                parts.append(block[:remain] + "\n…[обрезано]")
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)
