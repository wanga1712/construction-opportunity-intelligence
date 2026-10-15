"""Deterministic section/chapter detection for estimates and ВОР.

SECTION_LEVEL_NORMALIZATION_V1. Rows of a smeta carry the section identity in
column A ("Итого по главе 1", "Раздел 9 том 9.1.2 …") while the material name
sits in another column. The row-level extractor keeps the material but drops the
section label, so `structured_entities` cannot be grouped by section.

This module derives a deterministic section state, no model involved:

  * `section_code` / `section_name` from explicit markers
    ("Итого по главе N", "Раздел N[.M]", "Глава N");
  * `section_total_source` is ONLY `SECTION_TOTAL` (an explicit total row that
    itself carries a section marker) or `COMPUTED_SUM` (sum of the section's
    child line totals). Phase 1.5: a document/sheet-level total ("Итого:",
    "Всего с НДС") is a *document_total* and is NEVER assigned to a section;
  * facts with no marker fall into the visible `RESIDUE` section (nothing is
    dropped: input rows are all accounted for);
  * the sheet is tracked so "section" is `sheet × marker`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

SECTION_RESIDUE = "RESIDUE"
TOTAL_SECTION = "SECTION_TOTAL"
TOTAL_COMPUTED = "COMPUTED_SUM"

_CHAPTER_RE = re.compile(
    r"(?:итого\s+по\s+главе|итого\s+по\s+разделу|глава|раздел)"
    r"\s*№?\s*([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)
_TOTAL_RE = re.compile(r"^\s*(итого|всего)\b", re.IGNORECASE)
_PLAIN_NUMBER_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def parse_cell_number(cell: Any) -> Optional[float]:
    """A cell is a number only when the whole cell is one (no codes/dates)."""
    if cell is None:
        return None
    text = str(cell).replace("\u00a0", " ").replace(" ", "").strip()
    text = text.replace(",", ".")
    if not _PLAIN_NUMBER_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class SectionInfo:
    code: str
    name: str
    sheet: Optional[str] = None
    total_value: Optional[float] = None
    total_raw: Optional[str] = None
    total_source: Optional[str] = None
    computed_sum: float = 0.0
    children: int = 0


class SectionTracker:
    """Deterministic section state for one document (all its sheets)."""

    def __init__(self) -> None:
        self._sections: Dict[str, SectionInfo] = {}
        self._order: List[str] = []
        self._sheet: Optional[str] = None
        self._current: Optional[str] = None
        # Phase 1.5: document/sheet-level totals live OUTSIDE the section context.
        self.document_totals: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------- helpers
    @staticmethod
    def marker(cells: Sequence[Any]) -> Optional[str]:
        for cell in cells or ():
            match = _CHAPTER_RE.search(str(cell))
            if match:
                return " ".join(match.group(0).split())
        return None

    @staticmethod
    def _explicit_total(cells: Sequence[Any]) -> Optional[Dict[str, Any]]:
        """(value, raw) of an explicit 'Итого'/'Всего' row, if any.

        Smeta sheets carry two shapes:
          * a real total row — label + unit word + value, few cells
            (e.g. "Итого:", "руб.", "7450714594");
          * a merged label row — "Итого по главе N" sits in column A next to a
            material position and its own numbers, so its value is NOT the
            section total. Those rows are rejected by the cell-count guard.
        The value is the LAST numeric cell (totals live in the rightmost column).
        """
        cells = list(cells or ())
        if len(cells) > 4:
            return None
        label = None
        for cell in cells:
            text = str(cell).strip()
            if _TOTAL_RE.match(text):
                label = text
                break
        if label is None:
            return None
        value = None
        for cell in reversed(cells):
            value = parse_cell_number(cell)
            if value is not None:
                break
        if value is None:
            return None
        return {"value": value, "raw": label}

    def _section(self, code: str, name: str, sheet: Optional[str]) -> SectionInfo:
        info = self._sections.get(code)
        if info is None:
            info = SectionInfo(code=code, name=name, sheet=sheet)
            self._sections[code] = info
            self._order.append(code)
        return info

    # -------------------------------------------------------------- public
    def observe(
        self, sheet: Optional[str], cells: Sequence[Any], row_text: str = ""
    ) -> Optional[str]:
        """Update the section state for one row and return the active section."""
        if sheet != self._sheet:
            self._sheet = sheet
            self._current = None

        marker = self.marker(cells)
        if marker:
            code = f"{sheet or '-'}::{marker.lower()}"
            self._current = code
            info = self._section(code, marker, sheet)
            total = self._explicit_total(cells)
            if total is not None:
                # An explicit section/chapter total row ("Итого по главе N": value).
                info.total_value = total["value"]
                info.total_raw = total["raw"]
                info.total_source = TOTAL_SECTION
            return code

        total = self._explicit_total(cells)
        if total is not None:
            # Phase 1.5: document/sheet-level total ("Итого:", "Всего с НДС").
            # It is NOT a section total and must not leak into section_total_value.
            self.document_totals.setdefault(sheet or "-", {
                "value": total["value"], "raw": total["raw"],
            })
        return self._current

    def add_child(self, code: Optional[str], line_total: Optional[float]) -> None:
        if not code:
            return
        info = self._sections.get(code)
        if info is None:
            return
        info.children += 1
        if line_total is not None:
            info.computed_sum += float(line_total)

    def section(self, code: Optional[str]) -> Optional[SectionInfo]:
        if not code:
            return None
        return self._sections.get(code)

    def finalize(self) -> List[SectionInfo]:
        for info in self._sections.values():
            if info.total_source is None:
                info.total_source = TOTAL_COMPUTED
                info.total_value = round(info.computed_sum, 2)
        return [self._sections[code] for code in self._order]
