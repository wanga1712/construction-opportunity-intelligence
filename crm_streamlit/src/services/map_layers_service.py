"""
Слои карты: NSPD, NashDom, закупки 44/223/615 из CRM-индекса.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from src.services.geo_coords import normalize_coords
from src.services.map_export import MapFilters, fetch_map_objects, rows_to_geojson
from src.services.parking_db import ParkingDatabase

# Цвета слоёв
LAYER_COLORS = {
    "nspd": "#2e7d32",
    "nashdom": "#2066B0",
    "44fz": "#EA580C",
    "223fz": "#7C3AED",
    "615pp": "#0E7490",
}

LAYER_LABELS = {
    "nspd": "НСПД (кадастр)",
    "nashdom": "NashDom",
    "44fz": "44-ФЗ",
    "223fz": "223-ФЗ",
    "615pp": "615 ПП",
}

SOURCE_TO_LAYER = {
    "nashdom": "nashdom",
    "44fz": "44fz",
    "223fz": "223fz",
    "615pp": "615pp",
}


def _feature(
    lat: float,
    lon: float,
    *,
    layer: str,
    title: str,
    address: str = "",
    extra: Optional[dict] = None,
) -> dict:
    props = {
        "source_layer": layer,
        "source_label": LAYER_LABELS.get(layer, layer),
        "marker_color": LAYER_COLORS.get(layer, "#64748B"),
        "marker_radius": 7,
        "name": title,
        "address": address,
    }
    if extra:
        props.update(extra)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def _load_nspd_layer(
    parking_db: ParkingDatabase,
    min_floors: int,
    uk_status: str = "ALL",
) -> List[dict]:
    filters = MapFilters(min_floors=min_floors, uk_status=uk_status, limit=8000)
    rows = fetch_map_objects(parking_db, filters)
    features = []
    for row in rows:
        coords = normalize_coords(row.get("lat"), row.get("lon"))
        if not coords:
            continue
        lat, lon = coords
        features.append(_feature(
            lat, lon,
            layer="nspd",
            title=row.get("name") or row.get("address") or "НСПД объект",
            address=row.get("address") or "",
            extra={
                "cadastral_number": row.get("cadastral_number"),
                "purpose": row.get("purpose"),
                "object_type": row.get("object_type"),
                "wall_material": row.get("wall_material"),
                "area_total": row.get("area_total"),
                "floors_total": row.get("floors_total"),
                "floors_underground": row.get("floors_underground"),
                "parking_type": row.get("parking_type"),
                "confidence_score": row.get("confidence_score"),
                "candidate_reason": row.get("candidate_reason"),
                "uk_status": row.get("uk_status"),
                "management_type": row.get("management_type"),
                "uk_error": row.get("uk_error"),
                "uk_name": row.get("uk_name"),
                "uk_ogrn": row.get("uk_ogrn"),
                "hydro_grade": row.get("hydro_grade"),
                "hydro_label": row.get("hydro_label"),
                "hydro_icon": row.get("hydro_icon"),
                "hydro_score": row.get("hydro_score"),
                "hydro_reasons": row.get("hydro_reasons"),
                "marker_color": row.get("marker_color"),
                "marker_radius": row.get("marker_radius"),
                "object_id": row.get("object_id"),
            },
        ))
    return features


def _load_nashdom_layer(radar_db) -> List[dict]:
    try:
        from modules.crm.repositories.radar_objects_repository import RadarObjectsRepository

        repo = RadarObjectsRepository(radar_db)
        rows = repo.get_for_map()
    except Exception as e:
        logger.error(f"NashDom map layer: {e}")
        return []

    features = []
    for row in rows:
        coords = normalize_coords(row.get("latitude"), row.get("longitude"), swap_if_needed=True)
        if not coords:
            continue
        lat, lon = coords
        features.append(_feature(
            lat, lon,
            layer="nashdom",
            title=row.get("name") or "NashDom",
            address=row.get("address_text") or "",
            extra={
                "status": row.get("status_name"),
                "domrf_object_id": row.get("domrf_object_id"),
                "floors_total": row.get("floors_total"),
            },
        ))
    return features


def _radar_coords_map(radar_db, domrf_ids: List[str]) -> Dict[str, tuple[float, float]]:
    if not domrf_ids or not radar_db:
        return {}
    try:
        placeholders = ",".join(["%s"] * len(domrf_ids))
        rows = radar_db.execute_query(
            f"""
            SELECT domrf_object_id, latitude, longitude
            FROM mart_msk_pipeline_objects
            WHERE domrf_object_id IN ({placeholders})
              AND latitude IS NOT NULL AND longitude IS NOT NULL
            """,
            tuple(domrf_ids),
        )
        out = {}
        for r in rows:
            coords = normalize_coords(r.get("latitude"), r.get("longitude"))
            if coords:
                out[str(r["domrf_object_id"])] = coords
        return out
    except Exception as e:
        logger.error(f"radar coords batch: {e}")
        return {}


def _load_tender_layers(crm_db, radar_db, sources: Set[str]) -> tuple[List[dict], int]:
    """Объекты из crm_objects_index по источнику; координаты через domrf_object_id → radar."""
    if not crm_db or crm_db.is_offline_mode():
        return [], 0

    try:
        rows = crm_db.execute_query(
            "SELECT object_key, name, address, source_codes, domrf_object_id, registry_type, status, contract_number FROM crm_objects_index"
        ) or []
    except Exception as e:
        logger.error(f"tender map index: {e}")
        return [], 0

    need_sources = sources & {"44fz", "223fz", "615pp"}
    if not need_sources:
        return [], 0

    candidates = []
    no_coords = 0
    domrf_ids: List[str] = []

    for row in rows:
        codes = row.get("source_codes") or []
        if isinstance(codes, str):
            codes = json.loads(codes)
        layer = None
        for code in codes:
            if code in need_sources:
                layer = code
                break
        if not layer:
            continue
        domrf_id = row.get("domrf_object_id")
        if domrf_id:
            domrf_ids.append(str(domrf_id))
            candidates.append((row, layer, str(domrf_id)))
        else:
            no_coords += 1

    coord_map = _radar_coords_map(radar_db, list(set(domrf_ids)))
    features = []
    for row, layer, domrf_id in candidates:
        coords = coord_map.get(domrf_id)
        if not coords:
            no_coords += 1
            continue
        lat, lon = coords
        features.append(_feature(
            lat, lon,
            layer=layer,
            title=row.get("name") or "Закупка",
            address=row.get("address") or "",
            extra={
                "registry_type": row.get("registry_type"),
                "status": row.get("status"),
                "contract_number": row.get("contract_number"),
                "domrf_object_id": domrf_id,
                "object_key": row.get("object_key"),
            },
        ))
    return features, no_coords


def build_map_geojson(
    *,
    active_layers: Set[str],
    parking_db: Optional[ParkingDatabase] = None,
    radar_db=None,
    crm_db=None,
    min_floors: int = 0,
    uk_status: str = "ALL",
) -> tuple[dict, dict]:
    """
    Собрать GeoJSON и статистику по включённым слоям.

    Returns:
        (geojson, stats dict)
    """
    features: List[dict] = []
    stats: Dict[str, Any] = {
        "by_layer": {},
        "no_coords_tender": 0,
        "skipped_coords": 0,
    }

    if "nspd" in active_layers and parking_db and parking_db.connect():
        nspd_feats = _load_nspd_layer(parking_db, min_floors, uk_status=uk_status)
        features.extend(nspd_feats)
        stats["by_layer"]["nspd"] = len(nspd_feats)

    if "nashdom" in active_layers and radar_db:
        nd_feats = _load_nashdom_layer(radar_db)
        features.extend(nd_feats)
        stats["by_layer"]["nashdom"] = len(nd_feats)

    tender_sources = active_layers & {"44fz", "223fz", "615pp"}
    if tender_sources and crm_db:
        t_feats, no_coords = _load_tender_layers(crm_db, radar_db, tender_sources)
        features.extend(t_feats)
        stats["no_coords_tender"] = no_coords
        for layer in tender_sources:
            stats["by_layer"][layer] = sum(
                1 for f in t_feats if f["properties"].get("source_layer") == layer
            )

    stats["total"] = len(features)
    return {"type": "FeatureCollection", "features": features}, stats
