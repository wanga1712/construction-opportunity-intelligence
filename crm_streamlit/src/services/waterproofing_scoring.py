"""Scoring and filtering helpers for waterproofing CRM candidates."""
from __future__ import annotations

from typing import Iterable, List

from src.services.object_lifecycle import is_awarded
from src.services.object_models import ObjectViewItem
from src.services.objects_service import filter_objects
from src.services.hydro_zone_profiles import detect_hydro_zones
from src.services.waterproofing_process import calculate_score, priority_letter

HYDRO_KEYWORDS = (
    "гидроизоляц", "протеч", "подзем", "паркинг", "подвал", "техническ",
    "деформацион", "технологическ", "ввод", "трещин", "холодн", "шов",
    "инъект", "инъекц", "дренаж", "водоотвед", "капитальн", "ремонт",
)


def hydro_relevance(item: ObjectViewItem) -> int:
    """Return a 0-100 relevance score based on object and tender metadata."""
    text = " ".join(filter(None, [
        item.name, item.address, item.region, item.balance_holder,
        item.customer_name, item.search_text,
    ])).lower()
    score = sum(8 for keyword in HYDRO_KEYWORDS if keyword in text)
    if item.doc_matches:
        score += min(35, int(item.doc_matches))
    if item.matched_files:
        score += min(20, int(item.matched_files) * 3)
    if not is_awarded(item):
        score += 25
    if item.ai_priority_score:
        score += int(item.ai_priority_score) // 3
    zones = detect_hydro_zones(item)
    if zones:
        score += min(20, 6 * len(zones))
    return max(0, min(100, score))


def hydro_score(item: ObjectViewItem) -> tuple[int, list[str]]:
    """Return the CRM score and short human-readable reasons."""
    flags = {
        "documents": bool(item.doc_matches or item.matched_files),
        "check_3m": bool(item.doc_matches and item.doc_matches >= 5),
        "check_10m": bool(item.doc_matches and item.doc_matches >= 20),
        "tz_influence": not is_awarded(item),
        "no_contact": not bool(item.customer_name or item.balance_holder),
    }
    score = max(calculate_score(flags), hydro_relevance(item))
    reasons = []
    if not is_awarded(item):
        reasons.append("активная / неразыгранная")
    if item.doc_matches:
        reasons.append(f"совпадений: {item.doc_matches}")
    if item.matched_files:
        reasons.append(f"файлов: {item.matched_files}")
    if item.ai_priority_score:
        reasons.append(f"AI: {item.ai_priority_score}")
    zones = detect_hydro_zones(item)
    if zones:
        reasons.append("зоны: " + ", ".join(zones))
    return max(0, min(100, score)), reasons or ["минимум данных"]


def candidate_objects(
    items: Iterable[ObjectViewItem], *, only_hydro: bool
) -> List[ObjectViewItem]:
    """Apply hydro relevance and the shared object ordering/filtering."""
    result = []
    for item in items:
        relevance = hydro_relevance(item)
        if only_hydro and relevance < 25:
            continue
        item.ai_priority_score = max(int(item.ai_priority_score or 0), relevance)
        result.append(item)
    return filter_objects(result)


__all__ = ["HYDRO_KEYWORDS", "candidate_objects", "hydro_relevance", "hydro_score", "priority_letter"]
