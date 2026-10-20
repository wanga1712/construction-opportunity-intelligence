"""Deterministic quantity/unit/total reconciliation for estimate rows.

The mapper is deliberately fail-closed:
  * COUNT-family quantities must be integral;
  * a total is accepted only when quantity * price proves it;
  * column candidates are selected by arithmetic, not by caption alone.
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Hashable, Optional, Sequence, Tuple


COUNT_UNITS = frozenset(
    {"PCS", "UNIT", "SET", "PACK", "ROLL", "BAG", "SHEET", "PAIR"}
)


def _position(key: Hashable) -> Optional[int]:
    if isinstance(key, int):
        return key
    text = str(key).upper()
    if text.isdigit():
        return int(text)
    value = 0
    for char in text:
        if "A" <= char <= "Z":
            value = value * 26 + ord(char) - 64
        else:
            return None
    return value or None


def quantity_for_unit(
    quantity: Any, unit_normalized: Optional[str]
) -> Optional[float]:
    """Return a usable quantity; reject fractional quantities for COUNT units."""
    if quantity is None:
        return None
    try:
        value = float(quantity)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if (unit_normalized or "").upper() in COUNT_UNITS:
        nearest = round(value)
        if not math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-9):
            return None
        return float(nearest)
    return value


def arithmetic_delta(quantity: float, price: float, total: float) -> float:
    """Relative delta of total versus quantity * price."""
    computed = float(quantity) * float(price)
    denominator = max(abs(float(total)), abs(computed), 1.0)
    return abs(float(total) - computed) / denominator


def select_arithmetic_pair(
    quantity: Optional[float],
    prices: Sequence[Tuple[Hashable, float]],
    totals: Sequence[Tuple[Hashable, float]],
    *,
    tolerance: float = 0.05,
) -> Optional[Tuple[Hashable, float, Hashable, float, float]]:
    """Select the best proven (price, total) pair.

    Returns ``(price_key, price, total_key, total, delta)``. When several pairs
    reconcile, the rightmost total, then rightmost price, wins. This prevents a
    base-price/base-total column from winning merely because it appears first.
    """
    if quantity is None:
        return None
    matches = []
    for price_key, price in prices:
        for total_key, total in totals:
            delta = arithmetic_delta(quantity, price, total)
            if delta <= tolerance:
                matches.append((price_key, price, total_key, total, delta))
    if not matches:
        return None
    return min(
        matches,
        key=lambda item: (
            item[4],
            -(_position(item[2]) or 0),
            -(_position(item[0]) or 0),
        ),
    )


def find_arithmetic_triple(
    numbers: Sequence[Tuple[Hashable, float]],
    *,
    tolerance: float = 0.05,
) -> Optional[
    Tuple[Hashable, float, Hashable, float, Hashable, float, float]
]:
    """Find ``qty, price, total`` in source order using arithmetic proof."""
    matches = []
    for qty_pos, price_pos, total_pos in combinations(range(len(numbers)), 3):
        qty_key, qty = numbers[qty_pos]
        price_key, price = numbers[price_pos]
        total_key, total = numbers[total_pos]
        delta = arithmetic_delta(qty, price, total)
        if delta <= tolerance:
            matches.append(
                (qty_key, qty, price_key, price, total_key, total, delta)
            )
    if not matches:
        return None
    return min(
        matches,
        key=lambda item: (
            item[6],
            -(_position(item[4]) or 0),
            -(_position(item[2]) or 0),
        ),
    )


def nearest_unit(
    unit_values: Sequence[Tuple[Hashable, str, Optional[str], Optional[str]]],
    anchor: Optional[Hashable],
) -> Optional[Tuple[Hashable, str, Optional[str], Optional[str]]]:
    """Choose a normalized unit nearest to the quantity column/cell."""
    if not unit_values:
        return None
    if anchor is None:
        return unit_values[0]

    def distance(item):
        anchor_position = _position(anchor)
        item_position = _position(item[0])
        if anchor_position is None or item_position is None:
            return 0
        return abs(item_position - anchor_position)

    return min(unit_values, key=distance)
