from pathlib import Path
from typing import Dict, Type, Optional

from .parsers import BaseParser, PdfParser, WordParser, DocParser, ExcelParser, TextParser, OdtParser, GsfxParser


class ParserFactory:
    def __init__(self) -> None:
        self._parsers: Dict[str, Type[BaseParser]] = {
            ".pdf": PdfParser,
            ".docx": WordParser,
            ".doc": DocParser,
            ".xlsx": ExcelParser,
            ".xlsm": ExcelParser,
            ".odt": OdtParser,
            ".gsfx": GsfxParser,
            ".txt": TextParser,
            ".csv": TextParser,
        }

    def get_parser(self, path: Path) -> Optional[BaseParser]:
        suffix = path.suffix.lower()
        parser_cls = self._parsers.get(suffix)
        if not parser_cls:
            return None
        return parser_cls()
