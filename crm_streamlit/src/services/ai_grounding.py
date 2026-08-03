"""Ground AI answers on real document match products — never invent materials."""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.object_models import ObjectViewItem


def matched_product_names(match_files: Optional[Sequence[dict]] = None) -> List[str]:
    """Unique product names from tender_document_match_details only."""
    names: list[str] = []
    seen: set[str] = set()
    for file_row in match_files or []:
        for detail in file_row.get("details") or []:
            name = str(detail.get("product_name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
    return names


def evidence_snippets_from_match_files(
    match_files: Optional[Sequence[dict]] = None,
    *,
    limit: int = 6,
    max_chars: int = 350,
) -> List[str]:
    """Короткие фрагменты matched_display_text для промпта (цена/кол-во/ед.)."""
    out: list[str] = []
    seen: set[str] = set()
    for file_row in match_files or []:
        for detail in file_row.get("details") or []:
            raw = str(
                detail.get("text")
                or detail.get("matched_display_text")
                or detail.get("matched_text")
                or ""
            ).strip()
            if not raw:
                continue
            compact = " ".join(raw.split())
            if len(compact) > max_chars:
                compact = compact[: max_chars - 1] + "…"
            key = compact.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(compact)
            if len(out) >= limit:
                return out
    return out


def docs_processed_summary(doc_matches: int | None, matched_files: int | None) -> str:
    hits = int(doc_matches or 0)
    files = int(matched_files or 0)
    if hits <= 0 and files <= 0:
        return (
            "Документы по этой закупке ещё не дали подтверждённых совпадений "
            "(doc_matches=0, matched_files=0). Материалы из документов НЕ найдены."
        )
    return f"Совпадений в документах: {hits}; файлов с совпадениями: {files}."


def materials_block_for_prompt(
    *,
    doc_matches: int | None,
    matched_files: int | None,
    match_files: Optional[Sequence[dict]] = None,
    product_names: Optional[Sequence[str]] = None,
    volume_preview: Optional[str] = None,
    evidence_snippets: Optional[Sequence[str]] = None,
) -> str:
    products = [str(x).strip() for x in (product_names or []) if str(x).strip()]
    if not products:
        products = matched_product_names(match_files)
    snippets = [str(x).strip() for x in (evidence_snippets or []) if str(x).strip()]
    if not snippets:
        snippets = evidence_snippets_from_match_files(match_files)
    status = docs_processed_summary(doc_matches, matched_files)
    vol = (volume_preview or "").strip()
    if not products:
        return (
            f"{status}\n"
            "Подтверждённые материалы из документов: []\n"
            "Фрагменты строк сметы/ТЗ: []\n"
            "ЗАПРЕТ: materials_found должен быть []. Нельзя называть материалы "
            "из названия закупки, ОКПД, каталога или общих знаний."
        )
    listed = "; ".join(products[:40])
    lines = [
        status,
        f"Подтверждённые материалы из документов (единственный допустимый список): [{listed}]",
        "materials_found — только подмножество этого списка; иначе [].",
    ]
    if vol and "не извлеч" not in vol.lower():
        lines.append(f"Извлечённый объём/кол-во из строк совпадений: {vol}")
    else:
        lines.append("Извлечённый объём/кол-во: неизвестно (не выдумывать).")
    if snippets:
        lines.append("Фрагменты строк сметы/ТЗ (цены, ед., кол-во — только отсюда):")
        for idx, snip in enumerate(snippets[:8], 1):
            lines.append(f"  {idx}) {snip}")
    else:
        lines.append("Фрагменты строк сметы/ТЗ: [] — цены и характеристики не подтверждены.")
    return "\n".join(lines)


def materials_block_for_item(item: "ObjectViewItem") -> str:
    """Grounding для батч-классификатора по полям ObjectViewItem."""
    products = list(getattr(item, "matched_products_ai", None) or []) or list(
        getattr(item, "matched_product_preview", None) or []
    )
    return materials_block_for_prompt(
        doc_matches=getattr(item, "doc_matches", 0),
        matched_files=getattr(item, "matched_files", 0),
        product_names=products,
        volume_preview=getattr(item, "docs_volume_preview", None),
        evidence_snippets=getattr(item, "docs_evidence_preview", None),
    )


def sanitize_materials_found(
    materials: Any,
    *,
    allowed: Iterable[str],
    doc_matches: int | None = None,
) -> list[str]:
    """Drop hallucinated material names not present in match details."""
    if int(doc_matches or 0) <= 0:
        return []
    allowed_map = {a.lower(): a for a in allowed}
    if not allowed_map:
        return []
    out: list[str] = []
    for raw in materials or []:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in allowed_map:
            out.append(allowed_map[key])
            continue
        # soft contain: model may shorten product name
        hit = next((orig for low, orig in allowed_map.items() if low in key or key in low), None)
        if hit:
            out.append(hit)
    return list(dict.fromkeys(out))
