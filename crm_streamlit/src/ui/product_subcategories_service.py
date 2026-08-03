"""Справочник товарных категорий и подкатегорий для аналитических контуров."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from loguru import logger

DDL = """
CREATE TABLE IF NOT EXISTS crm_product_categories (
    id BIGSERIAL PRIMARY KEY,
    contour_code TEXT NOT NULL,
    category_code TEXT NOT NULL,
    category_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (contour_code, category_code)
);

CREATE TABLE IF NOT EXISTS crm_product_subcategories (
    id BIGSERIAL PRIMARY KEY,
    category_id BIGINT NOT NULL REFERENCES crm_product_categories(id) ON DELETE CASCADE,
    subcategory_code TEXT NOT NULL,
    subcategory_name TEXT NOT NULL,
    search_phrases JSONB NOT NULL DEFAULT '[]'::jsonb,
    negative_phrases JSONB NOT NULL DEFAULT '[]'::jsonb,
    technical_parameters JSONB NOT NULL DEFAULT '[]'::jsonb,
    brand_phrases JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL DEFAULT 'seed',
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (category_id, subcategory_code)
);
"""

_SCHEMA_READY = False

_CATEGORY_SEEDS: List[dict[str, Any]] = [
    {"contour_code": "procurement", "category_code": "lighting", "category_name": "Светотехника", "sort_order": 10},
    {"contour_code": "procurement", "category_code": "waterproofing", "category_name": "Гидроизоляция", "sort_order": 20},
    {"contour_code": "procurement", "category_code": "flooring", "category_name": "Напольные покрытия", "sort_order": 30},
    {"contour_code": "procurement", "category_code": "composites", "category_name": "Композиты", "sort_order": 40},
    {"contour_code": "computers", "category_code": "computers", "category_name": "Компьютеры и комплектующие", "sort_order": 10},
]

_COMMON_LIGHTING_PARAMS = [
    "мощность",
    "световой поток",
    "цветовая температура",
    "индекс цветопередачи",
    "степень защиты IP",
    "степень защиты IK",
    "напряжение питания",
    "тип монтажа",
    "габариты",
    "материал корпуса",
]

_LIGHTING_SUBCATEGORY_SEEDS: List[dict[str, Any]] = [
    {"code": "office_admin", "name": "Офисное и административное", "search": ["офисные светильники", "административные помещения", "армстронг", "595x595"]},
    {"code": "industrial_warehouse", "name": "Промышленное и складское", "search": ["складские светильники", "промышленные светильники", "high bay"]},
    {"code": "road_street", "name": "Автодорожное и уличное", "search": ["уличные светильники", "опоры освещения", "дорожное освещение"]},
    {"code": "tunnel", "name": "Тоннельное", "search": ["тоннельные светильники", "освещение тоннеля"]},
    {"code": "park_landscape", "name": "Парковое и ландшафтное", "search": ["парковые светильники", "ландшафтное освещение", "болларды"]},
    {"code": "facade_arch", "name": "Архитектурное и фасадное", "search": ["фасадное освещение", "архитектурная подсветка", "медиафасад"]},
    {"code": "emergency_evac", "name": "Аварийное и эвакуационное", "search": ["аварийные светильники", "эвакуационное освещение", "бап"]},
    {"code": "housing_public", "name": "ЖКХ и общественные зоны", "search": ["жкх светильники", "подъездные светильники", "дворовое освещение"]},
    {"code": "linear_indoor", "name": "Линейное внутреннее", "search": ["линейные светильники", "линейное освещение", "магистральные светильники"]},
    {"code": "downlights", "name": "Даунлайты и точечное", "search": ["даунлайт", "точечные светильники", "встраиваемые светильники"]},
    {"code": "floodlights", "name": "Прожекторы", "search": ["прожекторы", "заливающее освещение"]},
    {"code": "education", "name": "Образовательные учреждения", "search": ["освещение школы", "освещение детского сада", "освещение учебных классов"]},
    {"code": "medical_clean", "name": "Медицинские и чистые помещения", "search": ["медицинские светильники", "чистые помещения", "бактерицидные"]},
    {"code": "explosion_proof", "name": "Взрывозащищённое", "search": ["взрывозащищенные светильники", "ex светильники", "atex"]},
]


def _json_text(value: Any) -> str:
    """Сериализуем Python-структуру в JSON для записи в БД."""
    return json.dumps(value or [], ensure_ascii=False)


def ensure_schema(crm_db) -> bool:
    """Создаём таблицы справочника, если их ещё нет."""
    global _SCHEMA_READY
    if not crm_db:
        return False
    if _SCHEMA_READY:
        return True
    try:
        crm_db.execute_update(DDL)
        _SCHEMA_READY = True
        return True
    except Exception as exc:
        logger.warning(f"product_subcategories ensure_schema failed: {exc}")
        return False


def seed_defaults(crm_db) -> bool:
    """Заполняем стартовые категории и световые подкатегории."""
    if not crm_db or not ensure_schema(crm_db):
        return False
    try:
        for category in _CATEGORY_SEEDS:
            crm_db.execute_update(
                """
                INSERT INTO crm_product_categories (contour_code, category_code, category_name, sort_order)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (contour_code, category_code) DO UPDATE SET
                    category_name = EXCLUDED.category_name,
                    sort_order = EXCLUDED.sort_order,
                    is_active = TRUE,
                    updated_at = NOW()
                """,
                (category["contour_code"], category["category_code"], category["category_name"], category["sort_order"]),
            )

        rows = crm_db.execute_query(
            """
            SELECT id
            FROM crm_product_categories
            WHERE contour_code = 'procurement' AND category_code = 'lighting'
            LIMIT 1
            """
        ) or []
        if not rows:
            return False
        lighting_id = rows[0]["id"]

        for index, subcategory in enumerate(_LIGHTING_SUBCATEGORY_SEEDS, start=1):
            crm_db.execute_update(
                """
                INSERT INTO crm_product_subcategories (
                    category_id, subcategory_code, subcategory_name,
                    search_phrases, negative_phrases, technical_parameters, brand_phrases,
                    source, sort_order
                )
                VALUES (%s, %s, %s, %s::jsonb, '[]'::jsonb, %s::jsonb, '[]'::jsonb, 'seed', %s)
                ON CONFLICT (category_id, subcategory_code) DO UPDATE SET
                    subcategory_name = EXCLUDED.subcategory_name,
                    search_phrases = EXCLUDED.search_phrases,
                    technical_parameters = EXCLUDED.technical_parameters,
                    is_active = TRUE,
                    sort_order = EXCLUDED.sort_order,
                    updated_at = NOW()
                """,
                (
                    lighting_id,
                    subcategory["code"],
                    subcategory["name"],
                    _json_text(subcategory["search"]),
                    _json_text(_COMMON_LIGHTING_PARAMS),
                    index * 10,
                ),
            )
        return True
    except Exception as exc:
        logger.warning(f"product_subcategories seed_defaults failed: {exc}")
        return False


def load_filter_options(crm_db, *, contour_code: str = "procurement") -> Dict[str, Any]:
    """Загружаем опции подкатегорий для v2-фильтров."""
    fallback = {"header_subcategories": ["Все подкатегории"], "sidebar_subcategories": []}
    if not crm_db or not ensure_schema(crm_db):
        return fallback
    seed_defaults(crm_db)
    rows = crm_db.execute_query(
        """
        SELECT
            c.category_name,
            s.subcategory_code,
            s.subcategory_name
        FROM crm_product_categories c
        LEFT JOIN crm_product_subcategories s ON s.category_id = c.id AND s.is_active = TRUE
        WHERE c.contour_code = %s AND c.is_active = TRUE
        ORDER BY c.sort_order, s.sort_order, s.subcategory_name
        """,
        (contour_code,),
    ) or []

    labels: List[str] = []
    for row in rows:
        category_name = str(row.get("category_name") or "").strip()
        sub_name = str(row.get("subcategory_name") or "").strip()
        if not category_name or not sub_name:
            continue
        labels.append(f"{category_name} / {sub_name}")
    labels = list(dict.fromkeys(labels))
    return {
        "header_subcategories": ["Все подкатегории"] + labels,
        "sidebar_subcategories": labels,
    }
