"""Нормализация координат: Web Mercator (НСПД) → WGS84."""
from __future__ import annotations

import math
from typing import Optional, Tuple

# Границы Москвы и МО (приблизительно)
MOSCOW_LAT_MIN = 55.0
MOSCOW_LAT_MAX = 56.2
MOSCOW_LON_MIN = 36.5
MOSCOW_LON_MAX = 38.5

_MERCATOR_HALF = 20037508.34


def _looks_like_mercator(lat_val: float, lon_val: float) -> bool:
    """В БД НСПД: колонка lat = Y mercator, lon = X mercator (метры)."""
    return abs(lat_val) > 90 or abs(lon_val) > 180


def looks_like_web_mercator(x: float, y: float) -> bool:
    """DB lon/lat columns may hold EPSG:3857 meters (x, y)."""
    return abs(x) > 180 or abs(y) > 90


def mercator_yx_to_wgs84(y_mercator: float, x_mercator: float) -> Tuple[float, float]:
    """Как в десктопном map_widget.py: lat-колонка = Y, lon-колонка = X."""
    lon_wgs = (float(x_mercator) / _MERCATOR_HALF) * 180.0
    lat_wgs = (
        math.atan(math.exp(float(y_mercator) / _MERCATOR_HALF * math.pi)) * 360.0 / math.pi
    ) - 90.0
    return lat_wgs, lon_wgs


def storage_xy_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    """Convert parking DB lon/lat columns to WGS84 (lat, lon).

    If values already look like degrees, treat column order as (lon, lat) → return (lat, lon).
    """
    if not looks_like_web_mercator(x, y):
        return float(y), float(x)
    return mercator_yx_to_wgs84(y_mercator=y, x_mercator=x)


def wgs84_to_storage_xy(lon: float, lat: float) -> Tuple[float, float]:
    """Convert Leaflet lon/lat to Web Mercator meters for DB bbox filters."""
    x = lon * _MERCATOR_HALF / 180.0
    lat_c = max(min(lat, 89.5), -89.5)
    y = math.log(math.tan((90.0 + lat_c) * math.pi / 360.0)) / (math.pi / 180.0)
    y = y * _MERCATOR_HALF / 180.0
    return x, y


def valid_lonlat(lon: float, lat: float) -> bool:
    return -180 <= lon <= 180 and -90 <= lat <= 90


def normalize_coords(
    lat_val: Optional[float],
    lon_val: Optional[float],
    *,
    swap_if_needed: bool = True,
) -> Optional[Tuple[float, float]]:
    """
    Вернуть (lat, lon) в WGS84 или None если координаты невалидны.
    """
    if lat_val is None or lon_val is None:
        return None
    try:
        lat_f = float(lat_val)
        lon_f = float(lon_val)
    except (TypeError, ValueError):
        return None

    if _looks_like_mercator(lat_f, lon_f):
        lat_f, lon_f = mercator_yx_to_wgs84(lat_f, lon_f)
    elif swap_if_needed:
        # Иногда lat/lon перепутаны в градусах (lon попал в lat)
        if (
            MOSCOW_LON_MIN <= lat_f <= MOSCOW_LON_MAX
            and MOSCOW_LAT_MIN <= lon_f <= MOSCOW_LAT_MAX
        ):
            lat_f, lon_f = lon_f, lat_f

    if not is_in_moscow_region(lat_f, lon_f):
        return None
    return lat_f, lon_f


def is_in_moscow_region(lat: float, lon: float) -> bool:
    return (
        MOSCOW_LAT_MIN <= lat <= MOSCOW_LAT_MAX
        and MOSCOW_LON_MIN <= lon <= MOSCOW_LON_MAX
    )
