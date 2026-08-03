from pathlib import Path
from typing import Any, Dict, Tuple

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from utils.logger_config import get_logger

from .table_row_builder import append_plain_line, append_table_row, dedupe_merged_cells


class WordParser:
    def __init__(self) -> None:
        self.logger = get_logger()

    def parse(self, path: Path) -> str:
        text, _ = self.parse_with_meta(path)
        return text

    def parse_with_meta(self, path: Path) -> Tuple[str, Dict[int, Dict[str, Any]]]:
        self.logger.info(f"WordParser: parsing {path.name}...")
        parts: list[str] = []
        line_meta: Dict[int, Dict[str, Any]] = {}
        try:
            document = docx.Document(str(path))
            para_count = 0
            table_rows = 0
            table_index = 0

            # Обход body в порядке документа: абзацы и таблицы чередуются
            for block in self._iter_block_items(document):
                if isinstance(block, Paragraph):
                    para_count += 1
                    append_plain_line(parts, line_meta, block.text or "")
                    if para_count % 1000 == 0:
                        self.logger.debug(
                            f"WordParser: processed {para_count} paragraphs in {path.name}"
                        )
                elif isinstance(block, Table):
                    table_index += 1
                    for row_index, row in enumerate(block.rows, start=1):
                        cells = dedupe_merged_cells([cell.text for cell in row.cells])
                        if not cells:
                            continue
                        append_table_row(
                            parts,
                            line_meta,
                            cells,
                            table_index=table_index,
                            row_index=row_index,
                            sheet_name=f"table_{table_index}",
                        )
                        table_rows += 1

            self.logger.info(
                f"WordParser: finished {path.name}, paragraphs={para_count}, "
                f"table_rows={table_rows}, lines={len(parts)}"
            )
            return "\n".join(parts), line_meta
        except Exception as exc:
            self.logger.error(f"WordParser error processing {path.name}: {exc}")
            return "", {}

    def _iter_block_items(self, document):
        """Итерирует абзацы и таблицы в порядке появления в документе."""
        parent = document.element.body
        for child in parent.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, document)
            elif child.tag == qn("w:tbl"):
                yield Table(child, document)
