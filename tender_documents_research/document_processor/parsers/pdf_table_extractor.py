"""Извлечение таблиц из PDF через pdfplumber."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from utils.logger_config import get_logger

from .table_row_builder import append_ocr_table_lines, append_plain_line, append_table_row


class PdfTableExtractor:
    def __init__(self) -> None:
        self.logger = get_logger()

    def extract_page(
        self,
        page: Any,
        page_number: int,
        parts: List[str],
        line_meta: Dict[int, Dict[str, Any]],
        *,
        include_plain_text: bool = True,
    ) -> Tuple[str, int]:
        """Добавляет таблицы и опционально plain text. Возвращает (plain_text, rows_added)."""
        rows_before = len(parts)
        plain_text = ""
        if include_plain_text:
            try:
                plain_text = page.extract_text() or ""
            except Exception as exc:
                self.logger.debug(f"PdfTableExtractor: extract_text page {page_number}: {exc}")

            if plain_text.strip():
                for line in plain_text.splitlines():
                    append_plain_line(parts, line_meta, line, page_number=page_number)

        table_index = 0
        try:
            tables = page.extract_tables() or []
        except Exception as exc:
            self.logger.debug(f"PdfTableExtractor: extract_tables page {page_number}: {exc}")
            tables = []

        for table in tables:
            table_index += 1
            for row_index, row in enumerate(table, start=1):
                cells = [str(cell or "").strip() for cell in row]
                if not any(cells):
                    continue
                append_table_row(
                    parts,
                    line_meta,
                    cells,
                    page_number=page_number,
                    table_index=table_index,
                    row_index=row_index,
                    sheet_name=f"page_{page_number}_table_{table_index}",
                )
        return plain_text, len(parts) - rows_before

    def extract_document(self, path) -> Tuple[str, Dict[int, Dict[str, Any]]]:
        """Полный проход по PDF-файлу."""
        parts: List[str] = []
        line_meta: Dict[int, Dict[str, Any]] = {}
        try:
            import pdfplumber
        except ImportError as exc:
            self.logger.error(f"pdfplumber не установлен: {exc}")
            return "", {}

        try:
            with pdfplumber.open(str(path)) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    self.extract_page(page, page_number, parts, line_meta)
        except Exception as exc:
            self.logger.error(f"PdfTableExtractor: ошибка {path}: {exc}")
            return "", {}

        return "\n".join(parts), line_meta

    def append_plain_page(
        self,
        page_text: str,
        page_number: int,
        parts: List[str],
        line_meta: Dict[int, Dict[str, Any]],
    ) -> None:
        for line in page_text.splitlines():
            append_plain_line(parts, line_meta, line, page_number=page_number)

    def append_ocr_page(
        self,
        page_text: str,
        page_number: int,
        parts: List[str],
        line_meta: Dict[int, Dict[str, Any]],
    ) -> None:
        """Добавляет OCR-текст страницы с выделением табличных строк."""
        if not page_text.strip():
            return
        append_ocr_table_lines(parts, line_meta, page_text, page_number=page_number)
