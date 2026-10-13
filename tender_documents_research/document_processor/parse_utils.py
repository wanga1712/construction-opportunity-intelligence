"""Единая точка вызова парсеров с поддержкой line_meta."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from document_processor.parsers import ExcelParser, WordParser
from document_processor.parsers.pdf_parser import PdfParser

_logger = logging.getLogger("parse_utils")


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


def _ocr_rotation_probe(path: Path) -> int:
    """Pick the page rotation (0/90/180/270) that yields the most readable text."""
    try:
        import pytesseract
        from pdf2image import convert_from_path

        img = convert_from_path(str(path), first_page=1, last_page=1, dpi=120)[0]
    except Exception as exc:  # noqa: BLE001
        _logger.warning("OCR rotation probe unavailable for %s: %s", path.name, exc)
        return 0

    keywords = (
        "наименован", "единиц", "кол-во", "стоимост", "смет", "пол", "разборк",
        "гэсн", "линолеум", "покрыти", "грунт", "мастик", "ремонт", "керамогр",
        "ведомост", "объем",
    )
    best_rot, best_score = 0, -1
    for rot in (0, 90, 180, 270):
        try:
            text = pytesseract.image_to_string(
                img.rotate(rot, expand=True), lang="rus+eng", config="--psm 6"
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("OCR rotation probe rot=%s failed: %s", rot, exc)
            continue
        low = text.lower()
        cyrillic_words = len(re.findall(r"[а-яё]{3,}", low))
        keyword_hits = sum(1 for kw in keywords if kw in low)
        score = cyrillic_words + keyword_hits * 15
        if score > best_score:
            best_rot, best_score = rot, score
    _logger.info("OCR rotation probe for %s: rot=%s score=%s", path.name, best_rot, best_score)
    return best_rot


def parse_pdf_with_ocr(path: Path) -> Tuple[str, Optional[Dict[int, Dict[str, Any]]]]:
    """PdfParser first, OCR fallback for scanned PDFs when ``ENABLE_OCR=1``.

    Scanned сметы/ВОР are frequently rotated, so the page rotation is probed once
    on the first page and applied to every page. OCR output goes through the same
    table-row builder as the plain parser and is cleaned with the existing OCR
    normalization (omoglyphs, letter/digit junctions).
    """
    try:
        text, meta = PdfParser().parse_with_meta(path)
    except Exception as exc:  # noqa: BLE001 - corrupt PDF must not kill the batch
        _logger.warning("plain PDF parse failed %s: %s", path.name, exc)
        text, meta = "", None
    if text.strip():
        return text, meta
    if os.getenv("ENABLE_OCR", "0") != "1":
        return text, meta
    try:
        import pdf2image
        import pytesseract
        from document_processor.matching.normalization import normalize_ocr_line
        from document_processor.parsers.table_row_builder import append_table_row
    except Exception as exc:  # noqa: BLE001
        _logger.warning("OCR fallback unavailable for %s: %s", path.name, exc)
        return text, meta

    try:
        info = pdf2image.pdfinfo_from_path(str(path))
        total_pages = int(info.get("Pages") or 0)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("cannot read page count for OCR %s: %s", path.name, exc)
        return text, meta

    max_pages = int(os.getenv("OCR_MAX_PAGES", "60"))
    if total_pages > max_pages:
        _logger.warning("OCR %s truncated to %d of %d pages", path.name, max_pages, total_pages)
        total_pages = max_pages

    rotation = _ocr_rotation_probe(path)
    parts: list[str] = []
    line_meta: Dict[int, Dict[str, Any]] = {}
    for page_idx in range(total_pages):
        try:
            images = pdf2image.convert_from_path(
                str(path), first_page=page_idx + 1, last_page=page_idx + 1, dpi=200
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("OCR render page %d failed for %s: %s", page_idx + 1, path.name, exc)
            continue
        for img in images:
            if rotation:
                img = img.rotate(rotation, expand=True)
            try:
                ocr_text = pytesseract.image_to_string(img, lang="rus+eng", config="--psm 6")
            except Exception as exc:  # noqa: BLE001
                _logger.warning("OCR page %d failed for %s: %s", page_idx + 1, path.name, exc)
                continue
            if ocr_text.strip():
                ocr_text = "\n".join(normalize_ocr_line(ln) for ln in ocr_text.splitlines())
                for line in ocr_text.splitlines():
                    line = line.strip()
                    if line:
                        # Single cell per OCR line: the смета-OCR parser needs the
                        # un-split line to recover name/unit/quantity.
                        append_table_row(
                            parts, line_meta, [line],
                            page_number=page_idx + 1, table_index=0,
                        )
    return "\n".join(parts), line_meta or None
