"""Category Registry Service — CRUD + versioning + STALE marking.

Единственный источник истины для crm_product_categories.
Не содержит бизнес-логики AI. Только хранение и версионирование.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("category_registry_service")

# ─── Системные enum-ы ────────────────────────────────────────────────────────

ALLOWED_ROUTES = [
    "CONSTRUCTION_BUILDING",
    "CONSTRUCTION_INFRASTRUCTURE",
    "DESIGN_ENGINEERING",
    "COMPUTERS_IT",
    "DIRECT_SUPPLY",
    "EXCLUDED",
]

ALLOWED_OBJECT_TYPES: List[str] = []  # открытый список — заполняется из БД

ALLOWED_PROCUREMENT_TYPES = [
    "supply_only",
    "works_with_embedded_materials",
    "installation_only",
    "design_only",
    "construction_only",
    "design_and_construction",
    "specialized_turnkey_complex",
    "service_only",
    "unclear",
]

ALLOWED_ROLES = [
    "PRIMARY_SUPPLY",
    "EMBEDDED_MATERIAL",
    "CONSUMABLE",
    "OBJECT_OF_RESEARCH",
    "AUXILIARY_CONTEXT",
    "ABSENT",
    "UNKNOWN",
]

ALLOWED_ENTRY_POINTS = [
    "DIRECT_SUPPLY",
    "SUPPLIER",
    "SUB_CONTRACTOR",
    "CONTRACTOR_PARTNER",
    "NO_ENTRY",
    "UNKNOWN",
]

ALLOWED_DOC_TYPES = [
    "TECHNICAL_SPEC",
    "DESIGN_DOCUMENTATION",
    "BILL_OF_QUANTITIES",
    "ESTIMATE",
    "LOCAL_ESTIMATE",
    "SPECIFICATION",
    "WORKING_DOCUMENTATION",
    "EQUIPMENT_LIST",
    "PRICE_APPENDIX",
    "OTHER",
]

ALLOWED_EXTRACTION_FIELDS = [
    "ITEM_NAME",
    "MANUFACTURER",
    "MODEL",
    "QUANTITY",
    "UNIT",
    "TECHNICAL_SPECS",
    "MATERIAL_UNIT_PRICE",
    "MATERIAL_TOTAL_PRICE",
    "INSTALLATION_PRICE",
    "WORK_PRICE",
]


# ─── Registry hash ────────────────────────────────────────────────────────────

def compute_registry_hash(categories: List[Dict[str, Any]]) -> str:
    """SHA-256 от сортированного JSON всех активных категорий."""
    payload = json.dumps(
        sorted(categories, key=lambda c: c.get("category_code", "")),
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ─── CRUD ─────────────────────────────────────────────────────────────────────

def get_all_categories(crm_db, include_inactive: bool = True) -> List[Dict[str, Any]]:
    """Загрузить все категории из crm_product_categories."""
    sql = """
        SELECT
            id, contour_code, category_code, category_name,
            description, is_active, sort_order,
            aliases, positive_signals, negative_contexts,
            applicable_routes, applicable_object_types, applicable_procurement_types,
            default_role, allowed_roles, commercial_entry_points,
            document_search_plan, section_search_plan, extraction_fields,
            registry_version, updated_by, updated_at
        FROM crm_product_categories
        {where}
        ORDER BY sort_order, category_code
    """.format(where="" if include_inactive else "WHERE is_active = TRUE")
    rows = crm_db.execute_query(sql) or []
    result = []
    for r in rows:
        row = dict(r) if isinstance(r, dict) else {}
        # Normalize JSONB fields to Python objects
        for jsonb_field in (
            "aliases", "positive_signals", "negative_contexts",
            "applicable_routes", "applicable_object_types", "applicable_procurement_types",
            "allowed_roles", "commercial_entry_points",
            "document_search_plan", "section_search_plan", "extraction_fields",
        ):
            val = row.get(jsonb_field)
            if isinstance(val, str):
                try:
                    row[jsonb_field] = json.loads(val)
                except Exception:
                    row[jsonb_field] = []
            elif val is None:
                row[jsonb_field] = []
        result.append(row)
    return result


def get_category_by_code(crm_db, category_code: str) -> Optional[Dict[str, Any]]:
    rows = crm_db.execute_query(
        """
        SELECT id, contour_code, category_code, category_name,
            description, is_active, sort_order,
            aliases, positive_signals, negative_contexts,
            applicable_routes, applicable_object_types, applicable_procurement_types,
            default_role, allowed_roles, commercial_entry_points,
            document_search_plan, section_search_plan, extraction_fields,
            registry_version, updated_by, updated_at
        FROM crm_product_categories WHERE category_code = %s
        """,
        (category_code,),
    ) or []
    if not rows:
        return None
    r = dict(rows[0]) if isinstance(rows[0], dict) else {}
    for jsonb_field in (
        "aliases", "positive_signals", "negative_contexts",
        "applicable_routes", "applicable_object_types", "applicable_procurement_types",
        "allowed_roles", "commercial_entry_points",
        "document_search_plan", "section_search_plan", "extraction_fields",
    ):
        val = r.get(jsonb_field)
        if isinstance(val, str):
            try:
                r[jsonb_field] = json.loads(val)
            except Exception:
                r[jsonb_field] = []
        elif val is None:
            r[jsonb_field] = []
    return r


def get_subcategories_for(crm_db, category_id: int) -> List[Dict[str, Any]]:
    rows = crm_db.execute_query(
        """
        SELECT id, category_id, subcategory_code, subcategory_name, is_active, sort_order
        FROM crm_product_subcategories
        WHERE category_id = %s
        ORDER BY sort_order, subcategory_code
        """,
        (category_id,),
    ) or []
    return [dict(r) if isinstance(r, dict) else {} for r in rows]


def create_category(
    crm_db,
    *,
    category_code: str,
    category_name: str,
    contour_code: str = "procurement",
    description: str = "",
    is_active: bool = False,
    sort_order: int = 9999,
    aliases: List[str] = None,
    positive_signals: List[str] = None,
    negative_contexts: List[str] = None,
    applicable_routes: List[str] = None,
    applicable_object_types: List[str] = None,
    applicable_procurement_types: List[str] = None,
    default_role: str = "EMBEDDED_MATERIAL",
    allowed_roles: List[str] = None,
    commercial_entry_points: List[str] = None,
    document_search_plan: List[Dict] = None,
    section_search_plan: List[Dict] = None,
    extraction_fields: List[str] = None,
    updated_by: str = "superuser",
) -> int:
    """Создать новую категорию. Возвращает новый id."""
    sql = """
        INSERT INTO crm_product_categories (
            category_code, category_name, contour_code, description, is_active, sort_order,
            aliases, positive_signals, negative_contexts,
            applicable_routes, applicable_object_types, applicable_procurement_types,
            default_role, allowed_roles, commercial_entry_points,
            document_search_plan, section_search_plan, extraction_fields,
            registry_version, updated_by
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            1, %s
        ) RETURNING id
    """
    result = crm_db.execute_query(
        sql,
        (
            category_code, category_name, contour_code, description, is_active, sort_order,
            json.dumps(aliases or [], ensure_ascii=False),
            json.dumps(positive_signals or [], ensure_ascii=False),
            json.dumps(negative_contexts or [], ensure_ascii=False),
            json.dumps(applicable_routes or [], ensure_ascii=False),
            json.dumps(applicable_object_types or [], ensure_ascii=False),
            json.dumps(applicable_procurement_types or [], ensure_ascii=False),
            default_role,
            json.dumps(allowed_roles or ["PRIMARY_SUPPLY", "EMBEDDED_MATERIAL"], ensure_ascii=False),
            json.dumps(commercial_entry_points or ["DIRECT_SUPPLY"], ensure_ascii=False),
            json.dumps(document_search_plan or [], ensure_ascii=False),
            json.dumps(section_search_plan or [], ensure_ascii=False),
            json.dumps(extraction_fields or [], ensure_ascii=False),
            updated_by,
        ),
    )
    if result and result[0]:
        row = result[0]
        return row["id"] if isinstance(row, dict) else row[0]
    raise RuntimeError("create_category: no id returned")


def update_category(
    crm_db,
    category_id: int,
    *,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    aliases: Optional[List[str]] = None,
    positive_signals: Optional[List[str]] = None,
    negative_contexts: Optional[List[str]] = None,
    applicable_routes: Optional[List[str]] = None,
    applicable_object_types: Optional[List[str]] = None,
    applicable_procurement_types: Optional[List[str]] = None,
    default_role: Optional[str] = None,
    allowed_roles: Optional[List[str]] = None,
    commercial_entry_points: Optional[List[str]] = None,
    document_search_plan: Optional[List[Dict]] = None,
    section_search_plan: Optional[List[Dict]] = None,
    extraction_fields: Optional[List[str]] = None,
    updated_by: str = "superuser",
) -> None:
    """Обновить категорию, увеличить registry_version."""
    fields = []
    params = []

    def _add(col, val, is_jsonb=False):
        if val is not None:
            fields.append(f"{col} = %s")
            params.append(json.dumps(val, ensure_ascii=False) if is_jsonb else val)

    _add("category_name", category_name)
    _add("description", description)
    _add("is_active", is_active)
    _add("aliases", aliases, True)
    _add("positive_signals", positive_signals, True)
    _add("negative_contexts", negative_contexts, True)
    _add("applicable_routes", applicable_routes, True)
    _add("applicable_object_types", applicable_object_types, True)
    _add("applicable_procurement_types", applicable_procurement_types, True)
    _add("default_role", default_role)
    _add("allowed_roles", allowed_roles, True)
    _add("commercial_entry_points", commercial_entry_points, True)
    _add("document_search_plan", document_search_plan, True)
    _add("section_search_plan", section_search_plan, True)
    _add("extraction_fields", extraction_fields, True)

    if not fields:
        return  # ничего не изменилось

    fields.append("registry_version = registry_version + 1")
    fields.append("updated_by = %s")
    fields.append("updated_at = NOW()")
    params.extend([updated_by, category_id])

    sql = f"UPDATE crm_product_categories SET {', '.join(fields)} WHERE id = %s"
    crm_db.execute_update(sql, tuple(params))


# ─── Registry versioning ──────────────────────────────────────────────────────

def bump_registry_version(
    crm_db,
    *,
    change_description: str = "",
    changed_by: str = "superuser",
    affected_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Увеличить глобальную версию реестра, пересчитать hash, записать в audit log.
    Возвращает {'version': int, 'hash': str}.
    """
    # Получить текущую версию
    cur_ver_rows = crm_db.execute_query(
        "SELECT value FROM crm_settings WHERE key = 'category_registry_version'"
    ) or []
    cur_ver = 1
    if cur_ver_rows:
        v = cur_ver_rows[0]
        try:
            cur_ver = int((v["value"] if isinstance(v, dict) else v[0]) or 1)
        except Exception:
            cur_ver = 1

    new_ver = cur_ver + 1

    # Пересчитать hash по активным категориям
    active_cats = get_all_categories(crm_db, include_inactive=False)
    new_hash = compute_registry_hash(active_cats)

    # Обновить настройки
    crm_db.execute_update(
        "UPDATE crm_settings SET value = %s WHERE key = 'category_registry_version'",
        (str(new_ver),),
    )
    crm_db.execute_update(
        "UPDATE crm_settings SET value = %s WHERE key = 'category_registry_hash'",
        (new_hash,),
    )

    # Записать в audit log
    crm_db.execute_update(
        """
        INSERT INTO crm_category_registry_versions
            (version, registry_hash, change_description, changed_by, affected_category_codes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            new_ver,
            new_hash,
            change_description,
            changed_by,
            json.dumps(affected_codes or [], ensure_ascii=False),
        ),
    )

    logger.info(f"Registry bumped to v{new_ver} hash={new_hash} by={changed_by}")
    return {"version": new_ver, "hash": new_hash}


def get_current_registry_version(crm_db) -> Dict[str, Any]:
    """Вернуть текущую версию и hash реестра."""
    rows = crm_db.execute_query(
        "SELECT key, value FROM crm_settings WHERE key IN ('category_registry_version','category_registry_hash')"
    ) or []
    result = {"version": 1, "hash": ""}
    for r in rows:
        k = r["key"] if isinstance(r, dict) else r[0]
        v = r["value"] if isinstance(r, dict) else r[1]
        if k == "category_registry_version":
            try:
                result["version"] = int(v or 1)
            except Exception:
                pass
        elif k == "category_registry_hash":
            result["hash"] = v or ""
    return result


def get_registry_history(crm_db, limit: int = 20) -> List[Dict[str, Any]]:
    rows = crm_db.execute_query(
        """
        SELECT version, registry_hash, change_description, changed_by, changed_at, affected_category_codes
        FROM crm_category_registry_versions
        ORDER BY version DESC
        LIMIT %s
        """,
        (limit,),
    ) or []
    return [dict(r) if isinstance(r, dict) else {} for r in rows]


# ─── STALE marking ────────────────────────────────────────────────────────────

def count_stale_candidates(crm_db, current_hash: str) -> int:
    """Сколько assessments станут STALE при следующем изменении реестра."""
    rows = crm_db.execute_query(
        """
        SELECT COUNT(DISTINCT procurement_id) as cnt
        FROM procurement_ai_assessments
        WHERE is_current = TRUE
          AND status = 'SUCCESS'
          AND (normalized_result->>'registry_hash' IS NULL
               OR normalized_result->>'registry_hash' != %s)
        """,
        (current_hash,),
    ) or []
    if rows:
        r = rows[0]
        return int((r["cnt"] if isinstance(r, dict) else r[0]) or 0)
    return 0


def preview_stale_objects(crm_db, current_hash: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Показать несколько объектов, которые станут STALE."""
    rows = crm_db.execute_query(
        """
        SELECT cp.id, cp.auction_name, cp.ai_assessment_status
        FROM crm_procurements cp
        JOIN procurement_ai_assessments ai ON ai.procurement_id = cp.id AND ai.is_current = TRUE
        WHERE ai.status = 'SUCCESS'
          AND (ai.normalized_result->>'registry_hash' IS NULL
               OR ai.normalized_result->>'registry_hash' != %s)
        LIMIT %s
        """,
        (current_hash, limit),
    ) or []
    return [dict(r) if isinstance(r, dict) else {} for r in rows]
