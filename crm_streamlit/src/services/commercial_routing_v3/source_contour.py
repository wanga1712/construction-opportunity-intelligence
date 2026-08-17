"""Source contour resolution from actual law/source fields."""
from __future__ import annotations

from src.domain.commercial_routing_v3 import SourceContour


def resolve_source_contour(*, source_table: str = "", law_type: str = "") -> SourceContour:
    """Map procurement source to PUBLIC_44FZ or CORPORATE_223FZ."""
    law = (law_type or "").upper().strip()
    table = (source_table or "").lower()

    if law == "223_FZ" or "223_fz" in table:
        return SourceContour.CORPORATE_223FZ
    if law in ("44_FZ", "615_PP") or "44_fz" in table or "615" in table:
        return SourceContour.PUBLIC_44FZ
    # 615 treated as public contour for routing purposes
    return SourceContour.UNKNOWN


def source_contour_field_name() -> str:
    return "source_contour"
