from pathlib import Path
from typing import Any, Dict, Tuple

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None


from .pdf_table_extractor import PdfTableExtractor


class PdfParser:
    def __init__(self) -> None:
        self._table_extractor = PdfTableExtractor()

    def parse(self, path: Path) -> str:
        text, _ = self.parse_with_meta(path)
        return text

    def parse_with_meta(self, path: Path) -> Tuple[str, Dict[int, Dict[str, Any]]]:
        text, line_meta = self._table_extractor.extract_document(path)
        if text.strip():
            return text, line_meta

        # Fallback без pdfplumber / пустой результат
        reader = PdfReader(str(path))
        parts: list[str] = []
        line_meta: Dict[int, Dict[str, Any]] = {}
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            if not page_text.strip():
                continue
            for line in page_text.splitlines():
                if line.strip():
                    parts.append(line.strip())
                    line_meta[len(parts)] = {"page_number": page_number}
        return "\n".join(parts), line_meta
