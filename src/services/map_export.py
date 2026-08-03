"""
Сборка GeoJSON и статистики для карты кадастровых объектов / УК.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from src.services.geo_coords import storage_xy_to_wgs84, valid_lonlat, wgs84_to_storage_xy
from src.services.map_hydro_classify import HYDRO_GRADE_COLORS, classify_hydro_object
from src.services.parking_db import ParkingDatabase

# Центр Москвы
DEFAULT_CENTER = (55.7558, 37.6173)

STATUS_COLORS = {
    "UK_NOT_FOUND": "#F59E0B",
    "HOUSE_NOT_FOUND": "#EF4444",
    "FAILED": "#F97316",
    "PENDING": "#94A3B8",
    "SKIPPED": "#CBD5E1",
}

BASE_OBJECT_SQL = """
SELECT
    co.id AS object_id,
    co.lat,
    co.lon,
    co.cadastral_number,
    co.name,
    co.purpose,
    co.object_type,
    co.address_text AS address,
    co.floors_underground,
    co.floors_total,
    co.construction_finish_year,
    co.commissioning_year,
    co.area_total,
    co.wall_material,
    pc.parking_type,
    pc.confidence_score,
    pc.candidate_reason,
    cm.status AS uk_status,
    cm.management_type,
    cm.error_text AS uk_error,
    mc.id AS uk_id,
    mc.name AS uk_name,
    mc.ogrn AS uk_ogrn,
    mc.inn AS uk_inn,
    mc.phone AS uk_phone
FROM cadastral_object co
JOIN parking_candidate pc ON pc.cadastral_object_id = co.id
LEFT JOIN cadastral_object_management cm ON cm.cadastral_object_id = co.id
LEFT JOIN management_company mc ON mc.id = cm.management_company_id
WHERE co.lat IS NOT NULL
  AND co.lon IS NOT NULL
  AND pc.parking_type = 'UNDERGROUND'
"""


def color_from_ogrn(ogrn: str) -> str:
    """Стабильный цвет по OGRN (одна УК — один оттенок)."""
    digest = hashlib.md5(ogrn.encode("utf-8")).hexdigest()
    hue = int(digest[:8], 16) % 360
    # HSL → hex (s=65%, l=42%)
    import colorsys

    r, g, b = colorsys.hls_to_rgb(hue / 360.0, 0.42, 0.65)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def marker_color(uk_status: Optional[str], uk_ogrn: Optional[str]) -> str:
    if uk_status == "DONE" and uk_ogrn:
        return color_from_ogrn(uk_ogrn)
    if uk_status in STATUS_COLORS:
        return STATUS_COLORS[uk_status]
    return STATUS_COLORS["PENDING"]


@dataclass
class MapFilters:
    min_floors: int = 0
    uk_status: str = "ALL"  # ALL | DONE | NO_UK | HAS_UK
    address_query: str = ""
    uk_ogrn: Optional[str] = None
    bbox: Optional[tuple[float, float, float, float]] = None  # min_lon, min_lat, max_lon, max_lat
    limit: int = 5000


def _build_where(filters: MapFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if filters.min_floors >= 2:
        clauses.append("co.floors_underground >= %s")
        params.append(filters.min_floors)
    elif filters.min_floors >= 1:
        clauses.append("co.floors_underground >= 1")

    if filters.uk_status == "DONE":
        clauses.append("cm.status = 'DONE' AND mc.id IS NOT NULL")
    elif filters.uk_status == "HAS_UK":
        clauses.append("cm.status = 'DONE' AND mc.id IS NOT NULL")
    elif filters.uk_status == "NO_UK":
        clauses.append("(cm.id IS NULL OR cm.status IN ('UK_NOT_FOUND', 'HOUSE_NOT_FOUND', 'PENDING', 'FAILED', 'SKIPPED'))")

    if filters.address_query.strip():
        clauses.append("co.address_text ILIKE %s")
        params.append(f"%{filters.address_query.strip()}%")

    if filters.uk_ogrn:
        clauses.append("mc.ogrn = %s")
        params.append(filters.uk_ogrn)

    if filters.bbox:
        min_lon, min_lat, max_lon, max_lat = filters.bbox
        min_x, min_y = wgs84_to_storage_xy(min_lon, min_lat)
        max_x, max_y = wgs84_to_storage_xy(max_lon, max_lat)
        clauses.append("co.lon BETWEEN %s AND %s AND co.lat BETWEEN %s AND %s")
        params.extend([min(min_x, max_x), max(min_x, max_x), min(min_y, max_y), max(min_y, max_y)])

    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


def fetch_map_objects(db: ParkingDatabase, filters: MapFilters) -> list[dict]:
    where, params = _build_where(filters)
    sql = (
        BASE_OBJECT_SQL
        + where
        + " ORDER BY co.id LIMIT %s"
    )
    params.append(filters.limit)
    rows = db.query_all(sql, tuple(params))
    for row in rows:
        row.update(classify_hydro_object(row))
        status = row.get("uk_status")
        ogrn = row.get("uk_ogrn")
        row["marker_color"] = HYDRO_GRADE_COLORS.get(row.get("hydro_grade")) or marker_color(status, ogrn)
        row["marker_radius"] = 6 + min(8, int((row.get("hydro_score") or 0) / 16))
    return rows


def fetch_uk_summary(db: ParkingDatabase, min_floors: int = 0) -> list[dict]:
    floor_clause = ""
    params: list[Any] = []
    if min_floors >= 2:
        floor_clause = " AND co.floors_underground >= %s"
        params.append(min_floors)

    sql = f"""
    SELECT
        mc.id AS uk_id,
        mc.ogrn AS uk_ogrn,
        mc.inn AS uk_inn,
        mc.name AS uk_name,
        mc.phone AS uk_phone,
        COUNT(co.id) AS object_count,
        COUNT(CASE WHEN co.floors_underground >= 2 THEN 1 END) AS ge2_floors
    FROM management_company mc
    JOIN cadastral_object_management cm
        ON cm.management_company_id = mc.id AND cm.status = 'DONE'
    JOIN cadastral_object co ON co.id = cm.cadastral_object_id
    JOIN parking_candidate pc ON pc.cadastral_object_id = co.id
    WHERE co.lat IS NOT NULL AND co.lon IS NOT NULL
      AND pc.parking_type = 'UNDERGROUND'
      {floor_clause}
    GROUP BY mc.id, mc.ogrn, mc.inn, mc.name, mc.phone
    ORDER BY object_count DESC
    """
    rows = db.query_all(sql, tuple(params) if params else None)
    for row in rows:
        ogrn = row.get("uk_ogrn") or ""
        row["marker_color"] = color_from_ogrn(ogrn) if ogrn else "#94A3B8"
    return rows


def fetch_map_stats(db: ParkingDatabase) -> dict:
    sql = """
    SELECT
        COUNT(*) AS total_candidates,
        COUNT(*) FILTER (WHERE co.lat IS NOT NULL AND co.lon IS NOT NULL) AS with_coords,
        COUNT(*) FILTER (WHERE co.floors_underground >= 2) AS ge2_floors,
        COUNT(*) FILTER (WHERE cm.status = 'DONE' AND mc.id IS NOT NULL) AS with_uk,
        COUNT(*) FILTER (WHERE cm.status = 'UK_NOT_FOUND') AS uk_not_found,
        COUNT(*) FILTER (WHERE cm.status = 'HOUSE_NOT_FOUND') AS house_not_found,
        COUNT(*) FILTER (WHERE cm.status = 'PENDING' OR cm.id IS NULL) AS pending
    FROM cadastral_object co
    JOIN parking_candidate pc ON pc.cadastral_object_id = co.id
    LEFT JOIN cadastral_object_management cm ON cm.cadastral_object_id = co.id
    LEFT JOIN management_company mc ON mc.id = cm.management_company_id
    WHERE pc.parking_type = 'UNDERGROUND'
    """
    row = db.query_one(sql)
    stats = row or {}
    grade_rows = fetch_map_objects(db, MapFilters(min_floors=0, uk_status="ALL", limit=20000))
    stats["grade_a"] = sum(1 for r in grade_rows if r.get("hydro_grade") == "A")
    stats["grade_b"] = sum(1 for r in grade_rows if r.get("hydro_grade") == "B")
    stats["grade_c"] = sum(1 for r in grade_rows if r.get("hydro_grade") == "C")
    stats["grade_d"] = sum(1 for r in grade_rows if r.get("hydro_grade") == "D")
    return stats


def rows_to_geojson(rows: list[dict]) -> dict:
    features = []
    for row in rows:
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        map_lat, map_lon = storage_xy_to_wgs84(float(lon), float(lat))
        if not valid_lonlat(map_lon, map_lat):
            continue
        props = {k: v for k, v in row.items() if k not in ("lat", "lon")}
        props["source_lat"] = float(lat)
        props["source_lon"] = float(lon)
        for key, val in list(props.items()):
            if hasattr(val, "isoformat"):
                props[key] = val.isoformat()
            elif val is not None and not isinstance(val, (str, int, float, bool)):
                props[key] = str(val)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [map_lon, map_lat]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


def geojson_dumps(rows: list[dict]) -> str:
    return json.dumps(rows_to_geojson(rows), ensure_ascii=False)
