"""Factual source-law / procurement contour from source_table (pre-AI authority).

Never ask human or model to infer 44-ФЗ / 223-ФЗ / 615-ПП when the source contour
already encodes it. Display only — zero per-card SQL.
"""
from __future__ import annotations

from typing import Any

# Contour codes (stable machine keys)
LAW_44 = "44-FZ"
LAW_223 = "223-FZ"
LAW_615 = "615-PP"
LAW_COMMERCIAL = "COMMERCIAL"
LAW_UNKNOWN = "UNKNOWN"

SOURCE_CONTOUR_VALUES = (LAW_44, LAW_223, LAW_615, LAW_COMMERCIAL, LAW_UNKNOWN)

_LAW_LABELS_RU = {
    LAW_44: "44-ФЗ",
    LAW_223: "223-ФЗ",
    LAW_615: "615-ПП",
    LAW_COMMERCIAL: "Коммерческая",
    LAW_UNKNOWN: "Источник не определён",
}

_CONTOUR_LABELS_RU = {
    LAW_44: "Государственная / муниципальная закупка",
    LAW_223: "Корпоративная закупка",
    LAW_615: "Капитальный ремонт МКД",
    LAW_COMMERCIAL: "Коммерческая закупка",
    LAW_UNKNOWN: "Контур не определён",
}

# Explicit commercial source_table tokens — only when factual authority exists.
# Do NOT infer commercial from title.
_COMMERCIAL_SOURCE_TOKENS = (
    "commercial",
    "kommerchesk",
    "b2b",
    "private_tender",
    "non_eis",
)


def resolve_source_contour(source_table: str | None) -> dict[str, str]:
    """Map already-loaded source_table → read-only contour view model."""
    raw = str(source_table or "").strip()
    lower = raw.lower()
    code = LAW_UNKNOWN
    if "615" in lower or "kapremont" in lower or "capital_repair" in lower:
        code = LAW_615
    elif "223" in lower:
        code = LAW_223
    elif "44" in lower:
        code = LAW_44
    elif raw and any(token in lower for token in _COMMERCIAL_SOURCE_TOKENS):
        code = LAW_COMMERCIAL
    return {
        "source_table": raw,
        "law_code": code,
        "law_label": _LAW_LABELS_RU[code],
        "contour_label": _CONTOUR_LABELS_RU[code],
        "display_line": f"{_LAW_LABELS_RU[code]} · {_CONTOUR_LABELS_RU[code]}",
        "card_primary": _LAW_LABELS_RU[code],
        "card_secondary": _CONTOUR_LABELS_RU[code],
    }


def source_law_label(source_table: str | None) -> str:
    """Backward-compatible short law label (used by older call sites)."""
    return resolve_source_contour(source_table)["law_label"]


def enrich_dataset_row(row: dict[str, Any], source_table: str | None) -> dict[str, Any]:
    contour = resolve_source_contour(source_table)
    out = dict(row)
    out["law"] = contour["law_label"]
    out["source_contour"] = contour["contour_label"]
    out["law_code"] = contour["law_code"]
    return out
