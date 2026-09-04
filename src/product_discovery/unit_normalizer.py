"""Unit normalization and physical quantity compatibility checks."""

from __future__ import annotations

import re
from typing import Optional

from src.product_discovery.dto import UnitCategory


RE_PCS = re.compile(r"^(шт|штук\w*|pcs|piece\w*|ед\b|ед\.|единиц\w*|мест\w*)$", re.IGNORECASE)
RE_LENGTH = re.compile(r"^(м\b|м\.|метр\w*|пог\.?\s*м\w*|п\.?м\.?|пм|км\b)$", re.IGNORECASE)
RE_AREA = re.compile(r"^(м2|м²|кв\.?\s*м\w*|кв\.?\s*метр\w*|га\b)$", re.IGNORECASE)
RE_VOLUME = re.compile(r"^(м3|м³|куб\.?\s*м\w*|куб\.?\s*метр\w*|л\b|литр\w*)$", re.IGNORECASE)
RE_WEIGHT = re.compile(r"^(кг\b|кг\.|килограмм\w*|т\b|т\.|тн\b|тн\.|тонн\w*|г\b|грамм\w*)$", re.IGNORECASE)
RE_SET = re.compile(r"^(компл\w*|набор\w*|комплект\w*)$", re.IGNORECASE)


def normalize_unit(raw_unit: Optional[str]) -> UnitCategory:
    """Standardizes raw measurement unit string into physical UnitCategory."""
    if not raw_unit:
        return UnitCategory.OTHER

    u = raw_unit.strip().lower()
    u = u.replace("ё", "е")
    u = u.rstrip(".")

    if RE_PCS.match(u):
        return UnitCategory.PCS
    if RE_LENGTH.match(u):
        return UnitCategory.LENGTH
    if RE_AREA.match(u):
        return UnitCategory.AREA
    if RE_VOLUME.match(u):
        return UnitCategory.VOLUME
    if RE_WEIGHT.match(u):
        return UnitCategory.WEIGHT
    if RE_SET.match(u):
        return UnitCategory.SET

    return UnitCategory.OTHER


def are_units_compatible(u1: UnitCategory, u2: UnitCategory) -> bool:
    """Verifies whether two unit categories represent mutually compatible physical dimensions.

    Guarantees CROSS_UNIT_QUANTITY_COMPARISON=NO (e.g. PCS cannot be compared to LENGTH).
    """
    if u1 == UnitCategory.OTHER or u2 == UnitCategory.OTHER:
        return False
    if u1 == u2:
        return True
    if u1 in (UnitCategory.PCS, UnitCategory.SET) and u2 in (UnitCategory.PCS, UnitCategory.SET):
        return True
    return False
