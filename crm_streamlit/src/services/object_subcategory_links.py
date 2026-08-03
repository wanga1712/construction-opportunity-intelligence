"""Связка объектов с товарными подкатегориями по фактам из документов."""
from __future__ import annotations

import json
from typing import Any

from loguru import logger

from src.services.docs_match_preview import confirmed_product_groups

DDL = """
CREATE TABLE IF NOT EXISTS crm_object_subcategory_links (
    id BIGSERIAL PRIMARY KEY,
    object_key TEXT NOT NULL,
    tender_id BIGINT,
    registry_type TEXT,
    contour_code TEXT NOT NULL,
    category_code TEXT NOT NULL,
    subcategory_code TEXT NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 0,
    matched_phrases JSONB NOT NULL DEFAULT '[]'::jsonb,
    matched_products JSONB NOT NULL DEFAULT '[]'::jsonb,
    matched_brands JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL DEFAULT 'docs_fact',
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (object_key, contour_code, category_code, subcategory_code)
);

CREATE INDEX IF NOT EXISTS ix_crm_object_subcategory_links_object
    ON crm_object_subcategory_links(object_key, contour_code);
"""

GROUP_TO_CATEGORY = {
    "lighting": "lighting",
    "waterproofing": "waterproofing",
    "flooring": "flooring",
    "self_leveling_floors": "flooring",
    "drainage": "drainage_water_management",
    "composites": "composites",
    "computers": "computers",
}

_READY = False


def _json_text(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def ensure_schema(crm_db) -> bool:
    """Создаём таблицу связей объектов и подкатегорий."""
    global _READY
    if not crm_db:
        return False
    if _READY:
        return True
    try:
        crm_db.execute_update(DDL)
        _READY = True
        return True
    except Exception as exc:
        logger.warning(f"object_subcategory_links ensure_schema failed: {exc}")
        return False


def _load_rules(crm_db, contour_code: str) -> dict[str, list[dict]]:
    """Читаем подкатегории и их фразы из отдельных таблиц."""
    rows = crm_db.execute_query(
        """
        SELECT
            c.category_code,
            s.subcategory_code,
            s.subcategory_name,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'term_type', t.term_type,
                        'phrase', t.phrase,
                        'weight', t.weight
                    )
                    ORDER BY t.weight DESC, t.phrase
                ) FILTER (WHERE t.id IS NOT NULL),
                '[]'::jsonb
            ) AS terms
        FROM crm_product_categories c
        JOIN crm_product_subcategories s
          ON s.category_id = c.id
         AND s.is_active = TRUE
        LEFT JOIN crm_product_subcategory_terms t
          ON t.subcategory_id = s.id
         AND t.is_active = TRUE
        WHERE c.contour_code = %s
          AND c.is_active = TRUE
        GROUP BY c.category_code, s.subcategory_code, s.subcategory_name, c.sort_order, s.sort_order
        ORDER BY c.sort_order, s.sort_order, s.subcategory_name
        """,
        (contour_code,),
    ) or []
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        search = []
        negative = []
        brands = []
        for term in row.get("terms") or []:
            phrase = str(term.get("phrase") or "").strip()
            if not phrase:
                continue
            if term.get("term_type") == "negative":
                negative.append(phrase)
            elif term.get("term_type") == "brand":
                brands.append(phrase)
            elif term.get("term_type") == "search":
                search.append(phrase)
        grouped.setdefault(str(row["category_code"]), []).append(
            {
                "subcategory_code": str(row["subcategory_code"]),
                "subcategory_name": str(row["subcategory_name"]),
                "search_phrases": search,
                "negative_phrases": negative,
                "brand_phrases": brands,
            }
        )
    return grouped


def _item_text(item) -> str:
    parts = []
    parts.extend(item.matched_product_preview or [])
    parts.extend(item.docs_evidence_preview or [])
    parts.extend(item.matched_products_ai or [])
    parts.extend([item.name, item.search_text, item.docs_preview_line])
    return " ".join(str(x or "") for x in parts).lower()


def _match_subcategory(rule: dict, text: str, matched_products: list[str]) -> dict | None:
    positives = [str(x).strip().lower() for x in (rule.get("search_phrases") or []) if str(x).strip()]
    negatives = [str(x).strip().lower() for x in (rule.get("negative_phrases") or []) if str(x).strip()]
    if negatives and any(token in text for token in negatives):
        return None
    matched_phrases = [token for token in positives if token in text]
    if not matched_phrases:
        return None
    confidence = min(100, 50 + len(matched_phrases) * 12 + len(matched_products) * 2)
    return {
        "subcategory_code": rule["subcategory_code"],
        "confidence": confidence,
        "matched_phrases": matched_phrases[:10],
        "matched_products": matched_products[:10],
        "matched_brands": [],
    }


def sync_for_items(crm_db, items, *, contour_code: str = "procurement") -> None:
    """Пересчитываем подкатегории объектов после обновления фактов из документов."""
    if not crm_db or not ensure_schema(crm_db):
        return
    rules_by_category = _load_rules(crm_db, contour_code)
    if not rules_by_category:
        return
    for item in items:
        groups = confirmed_product_groups(item)
        if not groups:
            continue
        category_codes = {GROUP_TO_CATEGORY[group] for group in groups if group in GROUP_TO_CATEGORY}
        if not category_codes:
            continue
        text = _item_text(item)
        object_links: list[dict] = []
        for category_code in category_codes:
            rules = rules_by_category.get(category_code) or []
            group_key = next((g for g in groups if GROUP_TO_CATEGORY.get(g) == category_code), "")
            matched_products = list((item.matched_products_by_group or {}).get(group_key, [])) or list(item.matched_product_preview or [])
            category_links = []
            for rule in rules:
                matched = _match_subcategory(rule, text, matched_products)
                if matched:
                    category_links.append(matched)
            category_links.sort(key=lambda row: row["confidence"], reverse=True)
            for index, link in enumerate(category_links):
                object_links.append(
                    {
                        "category_code": category_code,
                        "subcategory_code": link["subcategory_code"],
                        "confidence": link["confidence"],
                        "matched_phrases": link["matched_phrases"],
                        "matched_products": link["matched_products"],
                        "matched_brands": link["matched_brands"],
                        "is_primary": index == 0,
                    }
                )
        if not object_links:
            continue
        crm_db.execute_update(
            "DELETE FROM crm_object_subcategory_links WHERE object_key = %s AND contour_code = %s",
            (item.key, contour_code),
        )
        for link in object_links:
            crm_db.execute_update(
                """
                INSERT INTO crm_object_subcategory_links (
                    object_key, tender_id, registry_type, contour_code,
                    category_code, subcategory_code, confidence,
                    matched_phrases, matched_products, matched_brands,
                    source, is_primary, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, 'docs_fact', %s, NOW())
                ON CONFLICT (object_key, contour_code, category_code, subcategory_code) DO UPDATE SET
                    confidence = EXCLUDED.confidence,
                    matched_phrases = EXCLUDED.matched_phrases,
                    matched_products = EXCLUDED.matched_products,
                    matched_brands = EXCLUDED.matched_brands,
                    source = EXCLUDED.source,
                    is_primary = EXCLUDED.is_primary,
                    updated_at = NOW()
                """,
                (
                    item.key,
                    item.tender_id,
                    item.registry_type,
                    contour_code,
                    link["category_code"],
                    link["subcategory_code"],
                    link["confidence"],
                    _json_text(link["matched_phrases"]),
                    _json_text(link["matched_products"]),
                    _json_text(link["matched_brands"]),
                    bool(link["is_primary"]),
                ),
            )


def load_links_map(crm_db, object_keys: list[str], *, contour_code: str = "procurement") -> dict[str, list[dict]]:
    """Возвращаем подкатегории по объектам для карточек и фильтров."""
    if not crm_db or not object_keys or not ensure_schema(crm_db):
        return {}
    placeholders = ",".join(["%s"] * len(object_keys))
    rows = crm_db.execute_query(
        f"""
        SELECT l.object_key, l.category_code, l.subcategory_code, l.confidence,
               l.matched_phrases, l.matched_products, l.matched_brands, l.is_primary,
               s.subcategory_name, c.category_name
        FROM crm_object_subcategory_links l
        JOIN crm_product_categories c
          ON c.contour_code = l.contour_code AND c.category_code = l.category_code
        JOIN crm_product_subcategories s
          ON s.category_id = c.id AND s.subcategory_code = l.subcategory_code
        WHERE l.contour_code = %s
          AND l.object_key IN ({placeholders})
        ORDER BY l.object_key, l.is_primary DESC, l.confidence DESC
        """,
        (contour_code, *object_keys),
    ) or []
    result: dict[str, list[dict]] = {}
    for row in rows:
        result.setdefault(str(row["object_key"]), []).append(dict(row))
    return result
