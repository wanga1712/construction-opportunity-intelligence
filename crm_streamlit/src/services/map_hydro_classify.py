"""Business classification for waterproofing map objects."""
from __future__ import annotations

from datetime import date
from typing import Optional

HYDRO_GRADE_COLORS = {"A": "#DC2626", "B": "#EA580C", "C": "#2563EB", "D": "#64748B"}


def classify_hydro_object(row: dict) -> dict:
    floors_under = int(row.get("floors_underground") or 0)
    area = float(row.get("area_total") or 0)
    confidence = float(row.get("confidence_score") or 0)
    building_year = _building_year(row)
    building_age = date.today().year - building_year if building_year else None
    text = " ".join(str(row.get(key) or "") for key in ("name", "purpose", "address")).lower()
    non_residential = any(word in text for word in (
        "нежил", "торгов", "тц", "трц", "мфк", "офис", "бизнес", "гостиниц",
        "отель", "паркинг", "гараж", "административ", "обществен", "склад",
    ))
    residential = any(word in text for word in ("мкд", "жил", "многоквартир", "квартир")) and not non_residential
    social = any(word in text for word in ("школ", "детск", "больниц", "поликлиник", "храм", "церков"))
    score, reasons = 0, []
    if floors_under >= 3:
        score, reasons = 45, [f"{floors_under} подземных этажа"]
    elif floors_under == 2:
        score, reasons = 35, ["2 подземных этажа"]
    elif floors_under == 1:
        score, reasons = 22, ["есть подземный этаж"]
    if non_residential:
        score += 35; reasons.append("нежилой/коммерческий объект")
    elif residential and floors_under >= 2:
        score += 28; reasons.append("МКД с ≥2 подземными этажами")
    elif residential:
        score += 12; reasons.append("жилой объект с подземкой")
    elif social:
        score += 8; reasons.append("социальный объект")
    if area >= 50_000:
        score += 15; reasons.append("очень большая площадь")
    elif area >= 15_000:
        score += 9; reasons.append("крупная площадь")
    if building_age is not None:
        if building_age >= 50:
            score += 14
        elif building_age >= 30:
            score += 10
        elif building_age >= 20:
            score += 5
        elif building_age < 12:
            score -= 18
        if building_age >= 20 or building_age < 12:
            reasons.append(f"{'новое здание:' if building_age < 12 else 'возраст здания'} {building_age} лет")
    if confidence >= .9:
        score += 8; reasons.append("высокая уверенность паркинга")
    elif confidence >= .75:
        score += 4
    if row.get("uk_name"):
        score += 7; reasons.append("есть УК/ответственный контур")
    if non_residential and floors_under >= 1:
        grade, label, icon = "A", "Нежилое с подземкой", "🏢"
    elif residential and floors_under >= 2:
        grade, label, icon = "B", "МКД ≥2 подз. этажа", "🏘️"
    elif floors_under >= 1:
        grade, label, icon = "C", "Подземка / требует проверки", "🅿️"
    else:
        grade, label, icon = "D", "Слабый сигнал", "▫️"
    return {
        "hydro_grade": grade, "hydro_label": label, "hydro_icon": icon,
        "hydro_score": max(0, min(100, score)), "building_year": building_year,
        "building_age": building_age,
        "hydro_reasons": "; ".join(reasons[:5]) or row.get("candidate_reason") or "",
    }


def _building_year(row: dict) -> Optional[int]:
    for key in ("commissioning_year", "construction_finish_year"):
        try:
            year = int(row.get(key))
        except (TypeError, ValueError):
            continue
        if 1700 <= year <= date.today().year + 1:
            return year
    return None
