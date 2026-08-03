"""Единая точка вызова парсеров с поддержкой line_meta."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from document_processor.parsers import ExcelParser, WordParser
from document_processor.parsers.pdf_parser import PdfParser


def parse_file_with_meta(
    parser: object,
    path: Path,
) -> Tuple[str, Optional[Dict[int, Dict[str, Any]]]]:
    """Вызывает parse_with_meta если есть, иначе parse."""
    parse_with_meta = getattr(parser, "parse_with_meta", None)
    if callable(parse_with_meta):
        text, line_meta = parse_with_meta(path)
        return text, line_meta
    parse_fn = getattr(parser, "parse", None)
    if not callable(parse_fn):
        return "", None
    return parse_fn(path), None


def supports_rich_meta(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix in {".xlsx", ".xlsm", ".docx", ".pdf"}


def get_rich_parser(parser_factory, path: Path):
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return WordParser()
    if suffix == ".pdf":
        return PdfParser()
    if suffix in {".xlsx", ".xlsm"}:
        return ExcelParser()
    return parser_factory.get_parser(path)
