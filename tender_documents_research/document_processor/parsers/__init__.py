from pathlib import Path
from typing import Protocol

from .pdf_parser import PdfParser
from .word_parser import WordParser
from .doc_parser import DocParser
from .excel_parser import ExcelParser
from .text_parser import TextParser
from .odt_parser import OdtParser
from .gsfx_parser import GsfxParser


class BaseParser(Protocol):
    def parse(self, path: Path) -> str:
        ...

