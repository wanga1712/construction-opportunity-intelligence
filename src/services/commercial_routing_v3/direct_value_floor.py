"""Порог стоимости прямой поставки для медали (бизнес-правило).

Закупка ниже порога не может получить медаль выше указанной, даже если балл и
уверенность категории высокие: цель — не выдавать GOLD/SILVER закупкам на десятки
тысяч рублей. Порог работает только как hard cap (медаль может быть понижена, но
никогда не повышена) и применяется в двух местах: детерминированный скорер
(candidate_scoring.score_hypothesis) и track-медаль (medal.compute_track_medal),
чтобы правило было одинаковым независимо от того, какой путь посчитал медаль.

Пороги согласованы с оператором 10.10.2026:
    НМЦК отсутствует или <= 10 000 ₽  → не выше WOOD
    < 50 000 ₽                        → не выше BRONZE
    < 100 000 ₽                       → не выше SILVER
    >= 100 000 ₽                      → ограничения нет

Скоринг/пороги медалей по баллам (75/50/25) не меняются — добавляется только
стоимостной ограничитель для режима DIRECT_SUPPLY.
"""
from __future__ import annotations

from typing import Optional, Tuple

from src.domain.commercial_routing_v3 import CandidateMedal

_RANK = {
    CandidateMedal.GOLD: 4,
    CandidateMedal.SILVER: 3,
    CandidateMedal.BRONZE: 2,
    CandidateMedal.WOOD: 1,
}
_BY_RANK = {rank: medal for medal, rank in _RANK.items()}

NO_NMCK_REASON = "direct_value_floor_no_nmck"
#: (верхняя граница НМЦК, максимально допустимая медаль, код причины)
VALUE_FLOOR_STEPS: Tuple[Tuple[float, CandidateMedal, str], ...] = (
    (10_000.0, CandidateMedal.WOOD, "direct_value_floor_lt_10k"),
    (50_000.0, CandidateMedal.BRONZE, "direct_value_floor_lt_50k"),
    (100_000.0, CandidateMedal.SILVER, "direct_value_floor_lt_100k"),
)


def direct_value_cap(price: object) -> Tuple[Optional[CandidateMedal], Optional[str]]:
    """Максимально допустимая медаль по стоимости закупки."""
    try:
        value = float(price) if price is not None and price != "" else 0.0
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return CandidateMedal.WOOD, NO_NMCK_REASON
    for limit, medal, reason in VALUE_FLOOR_STEPS:
        if value < limit:
            return medal, reason
    return None, None


def lower_medal(first: Optional[CandidateMedal],
                second: Optional[CandidateMedal]) -> Optional[CandidateMedal]:
    """Более слабая из двух медалей (для объединения нескольких hard cap)."""
    if first is None:
        return second
    if second is None:
        return first
    return first if _RANK[first] <= _RANK[second] else second


def medal_rank(medal: Optional[CandidateMedal]) -> int:
    return _RANK.get(medal, 0)


def medal_by_rank(rank: int) -> CandidateMedal:
    return _BY_RANK.get(rank, CandidateMedal.WOOD)
