"""Pure formatting helpers and icon maps for object detail."""
from __future__ import annotations

from typing import Any, Dict, Optional

_SEGMENT_ICONS = {
    "residential": "🏠",
    "social": "🏛",
    "commercial": "🏬",
    "other": "📦",
}

_METRIC_ICONS = {
    "Совпадений": "🎯",
    "Файлов": "📁",
    "Файлов с совпадениями": "📁",
    "Всего совпадений": "🎯",
    "Уровень данных": "📊",
    "НМЦ": "💰",
    "Итог": "✅",
    "Итоговая": "✅",
    "Сегмент": "🏷️",
    "Начало": "▶️",
    "Окончание": "⏹️",
}

_SECTION_ICONS = {
    "Закупка": "📋",
    "Участники": "👥",
    "Что найдено в документах": "🔎",
    "Торги": "⚖️",
    "Поставка / исполнение": "🚚",
    "Цены": "💵",
    "Файлы закупки на площадке": "📎",
    "Экспертиза": "🧾",
    "NashDom": "🏗️",
}

_FIELD_ICONS = {
    "Реестр": "📑",
    "№ закупки": "🔢",
    "Регион поставки": "📍",
    "ОКПД": "🏷️",
    "Описание ОКПД": "📄",
    "Площадка": "🌐",
    "Ссылка площадки": "🔗",
    "Балансодержатель": "🏛️",
    "Организатор торгов": "🏢",
    "Победитель": "🏆",
}


def _doc_icon(file_name: str) -> str:
    lower = (file_name or "").lower()
    if lower.endswith(".pdf"):
        return "📕"
    if lower.endswith((".zip", ".rar", ".7z")):
        return "🗜️"
    if lower.endswith((".xlsx", ".xls")):
        return "📊"
    if lower.endswith((".docx", ".doc")):
        return "📝"
    return "📄"


def _fmt_price(val: Optional[float]) -> str:
    if val is None:
        return "—"
    try:
        v = float(val)
        if v >= 1_000_000:
            return f"{v / 1_000_000:.2f} млн ₽"
        return f"{v:,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return str(val)


def _truncate(text: str, limit: int = 220) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _location_cell(d: Dict[str, Any]) -> str:
    parts = []
    if d.get("sheet_name"):
        parts.append(str(d["sheet_name"]))
    if d.get("cell_address"):
        parts.append(str(d["cell_address"]))
    if d.get("line_number"):
        parts.append(f"стр. {d['line_number']}")
    return " / ".join(parts) or "—"
