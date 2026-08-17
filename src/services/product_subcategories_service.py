"""Справочник категорий, подкатегорий и поисковых фраз аналитического контура."""
from __future__ import annotations

import json
from typing import Any

from loguru import logger

from src.services.product_subcategory_seed_data import CATEGORY_SEEDS, SUBCATEGORY_SEEDS_BY_CATEGORY

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
    technical_parameters JSONB NOT NULL DEFAULT '[]'::jsonb,
    brand_phrases JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL DEFAULT 'seed',
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (category_id, subcategory_code)
);

CREATE TABLE IF NOT EXISTS crm_product_subcategory_terms (
    id BIGSERIAL PRIMARY KEY,
    subcategory_id BIGINT NOT NULL REFERENCES crm_product_subcategories(id) ON DELETE CASCADE,
    term_type TEXT NOT NULL,
    phrase TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 100,
    source TEXT NOT NULL DEFAULT 'seed',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (subcategory_id, term_type, phrase)
);

CREATE INDEX IF NOT EXISTS ix_crm_product_subcategory_terms_subcategory
    ON crm_product_subcategory_terms(subcategory_id, term_type, is_active);
"""

_SCHEMA_READY = False


def _category_contour_map() -> dict[str, str]:
    """Возвращаем связь category_code -> contour_code из seed-описания."""
    result: dict[str, str] = {}
    for category in CATEGORY_SEEDS:
        result[str(category["category_code"])] = str(category["contour_code"])
    return result


def _json_text(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def ensure_schema(crm_db) -> bool:
    """Fail-closed: tables must already exist. No runtime DDL."""
    global _SCHEMA_READY
    if not crm_db:
        return False
    if _SCHEMA_READY:
        return True
    from src.services.schema_guard import require_relations

    ok, missing = require_relations(
        crm_db,
        [
            "crm_product_categories",
            "crm_product_subcategories",
            "crm_product_subcategory_terms",
        ],
    )
    if not ok:
        logger.warning(f"product_subcategories SCHEMA_NOT_READY missing={missing}")
        return False
    _SCHEMA_READY = True
    return True


def _upsert_categories(crm_db) -> dict[str, int]:
    for category in CATEGORY_SEEDS:
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
        SELECT id, contour_code, category_code
        FROM crm_product_categories
        WHERE is_active = TRUE
        """
    ) or []
    return {f'{row["contour_code"]}:{row["category_code"]}': row["id"] for row in rows}


def _upsert_subcategories(crm_db, category_ids: dict[str, int]) -> dict[str, int]:
    subcategory_ids: dict[str, int] = {}
    contour_map = _category_contour_map()
    for category_code, config in SUBCATEGORY_SEEDS_BY_CATEGORY.items():
        contour_code = contour_map.get(category_code, "procurement")
        category_id = category_ids.get(f"{contour_code}:{category_code}")
        if not category_id:
            continue
        params = config.get("technical_parameters") or []
        for index, subcategory in enumerate(config.get("items") or [], start=1):
            crm_db.execute_update(
                """
                INSERT INTO crm_product_subcategories (
                    category_id, subcategory_code, subcategory_name,
                    technical_parameters, brand_phrases, source, sort_order
                )
                VALUES (%s, %s, %s, %s::jsonb, '[]'::jsonb, 'seed', %s)
                ON CONFLICT (category_id, subcategory_code) DO UPDATE SET
                    subcategory_name = EXCLUDED.subcategory_name,
                    technical_parameters = EXCLUDED.technical_parameters,
                    is_active = TRUE,
                    sort_order = EXCLUDED.sort_order,
                    updated_at = NOW()
                """,
                (
                    category_id,
                    subcategory["code"],
                    subcategory["name"],
                    _json_text(params),
                    index * 10,
                ),
            )
    rows = crm_db.execute_query(
        """
        SELECT s.id, c.contour_code, c.category_code, s.subcategory_code
        FROM crm_product_subcategories s
        JOIN crm_product_categories c ON c.id = s.category_id
        WHERE c.is_active = TRUE
          AND s.is_active = TRUE
        """
    ) or []
    for row in rows:
        subcategory_ids[f'{row["contour_code"]}:{row["category_code"]}:{row["subcategory_code"]}'] = row["id"]
    return subcategory_ids


def _sync_terms(crm_db, subcategory_ids: dict[str, int]) -> None:
    contour_map = _category_contour_map()
    for category_code, config in SUBCATEGORY_SEEDS_BY_CATEGORY.items():
        contour_code = contour_map.get(category_code, "procurement")
        for subcategory in config.get("items") or []:
            subcategory_id = subcategory_ids.get(f'{contour_code}:{category_code}:{subcategory["code"]}')
            if not subcategory_id:
                continue
            for phrase in subcategory.get("search") or []:
                crm_db.execute_update(
                    """
                    INSERT INTO crm_product_subcategory_terms (subcategory_id, term_type, phrase, weight, source, is_active)
                    VALUES (%s, 'search', %s, 100, 'seed', TRUE)
                    ON CONFLICT (subcategory_id, term_type, phrase) DO UPDATE SET
                        weight = EXCLUDED.weight,
                        is_active = TRUE,
                        updated_at = NOW()
                    """,
                    (subcategory_id, str(phrase).strip()),
                )
            for phrase in subcategory.get("negative") or []:
                crm_db.execute_update(
                    """
                    INSERT INTO crm_product_subcategory_terms (subcategory_id, term_type, phrase, weight, source, is_active)
                    VALUES (%s, 'negative', %s, 100, 'seed', TRUE)
                    ON CONFLICT (subcategory_id, term_type, phrase) DO UPDATE SET
                        weight = EXCLUDED.weight,
                        is_active = TRUE,
                        updated_at = NOW()
                    """,
                    (subcategory_id, str(phrase).strip()),
                )


def seed_defaults(crm_db) -> bool:
    """Заполняем категории, подкатегории и поисковые фразы."""
    if not crm_db or not ensure_schema(crm_db):
        return False
    try:
        category_ids = _upsert_categories(crm_db)
        subcategory_ids = _upsert_subcategories(crm_db, category_ids)
        _sync_terms(crm_db, subcategory_ids)
        return True
    except Exception as exc:
        logger.warning(f"product_subcategories seed_defaults failed: {exc}")
        return False


def load_filter_options(crm_db, *, contour_code: str = "procurement") -> dict[str, Any]:
    """Загружаем динамические опции подкатегорий для фильтров."""
    fallback = {"header_subcategories": ["Все подкатегории"], "sidebar_subcategories": []}
    if not crm_db or not ensure_schema(crm_db):
        return fallback
    seed_defaults(crm_db)
    rows = crm_db.execute_query(
        """
        SELECT c.category_name, s.subcategory_name
        FROM crm_product_categories c
        JOIN crm_product_subcategories s ON s.category_id = c.id AND s.is_active = TRUE
        WHERE c.contour_code = %s
          AND c.is_active = TRUE
        ORDER BY c.sort_order, s.sort_order, s.subcategory_name
        """,
        (contour_code,),
    ) or []
    labels = [f'{row["category_name"]} / {row["subcategory_name"]}' for row in rows if row.get("category_name") and row.get("subcategory_name")]
    labels = list(dict.fromkeys(labels))
    return {"header_subcategories": ["Все подкатегории"] + labels, "sidebar_subcategories": labels}
