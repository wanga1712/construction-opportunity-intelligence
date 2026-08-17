"""Commercial taxonomy registry loader.

Read-only service for dynamic registry consumers (future AI / matcher).
Does not change AI prompt or matcher behavior in COMMERCIAL-TAXONOMY-SCHEMA-AND-REGISTRY-1.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.domain.commercial_taxonomy import (
    CategoryLifecycleState,
    CategorySemanticType,
    DimensionType,
    EvidenceRole,
    SearchabilityMode,
    SignalClassification,
    TermSemanticType,
    is_valid_commercial_category_code,
)
from src.services.category_registry_service import compute_registry_hash, get_current_registry_version

logger = logging.getLogger("commercial_taxonomy_registry")

_CATEGORY_SELECT = """
    SELECT
        id, contour_code, category_code, category_name, description,
        is_active, sort_order, semantic_type, lifecycle_state,
        searchability_mode, legacy_compat_role, registry_version
    FROM crm_product_categories
    {where}
    ORDER BY sort_order, category_code
"""


def _row_dict(row: Any) -> Dict[str, Any]:
    return dict(row) if isinstance(row, dict) else {}


def normalize_term(term: str) -> str:
    return " ".join((term or "").strip().lower().split())


def load_active_commercial_categories(
    crm_db,
    *,
    allow_legacy_fallback: bool = False,
) -> List[Dict[str, Any]]:
    """Active commercial categories for AI/matcher dynamic registry (future consumers)."""
    try:
        rows = crm_db.execute_query(
            _CATEGORY_SELECT.format(where="""
                WHERE is_active = TRUE
                  AND semantic_type = 'COMMERCIAL_CATEGORY'
                  AND lifecycle_state IN ('ACTIVE', 'ACTIVE_AI_ONLY')
            """)
        ) or []
        return [_row_dict(r) for r in rows]
    except Exception as exc:
        if not allow_legacy_fallback:
            raise
        # Legacy compatibility fallback ONLY for tests/compat pipelines.
        logger.warning("Legacy fallback active category load (compat mode): %s", exc)
        rows = crm_db.execute_query(
            """
            SELECT
                id, contour_code, category_code, category_name, description,
                is_active, sort_order, registry_version
            FROM crm_product_categories
            WHERE is_active = TRUE
            ORDER BY sort_order, category_code
            """
        ) or []
        defaults = {
            "semantic_type": CategorySemanticType.COMMERCIAL_CATEGORY.value,
            "lifecycle_state": CategoryLifecycleState.ACTIVE.value,
            "searchability_mode": SearchabilityMode.DIRECT_SEARCHABLE.value,
            "legacy_compat_role": None,
        }
        out: List[Dict[str, Any]] = []
        for r in rows:
            item = _row_dict(r)
            item.update(defaults)
            out.append(item)
        return out


def load_all_categories_with_semantics(
    crm_db,
    *,
    include_inactive: bool = True,
    allow_legacy_fallback: bool = False,
) -> List[Dict[str, Any]]:
    where = "" if include_inactive else "WHERE is_active = TRUE"
    try:
        rows = crm_db.execute_query(_CATEGORY_SELECT.format(where=where)) or []
        return [_row_dict(r) for r in rows]
    except Exception as exc:
        if not allow_legacy_fallback:
            raise
        logger.warning("Legacy fallback full category load (compat mode): %s", exc)
        sql = """
            SELECT
                id, contour_code, category_code, category_name, description,
                is_active, sort_order, registry_version
            FROM crm_product_categories
        """
        if not include_inactive:
            sql += " WHERE is_active = TRUE"
        sql += " ORDER BY sort_order, category_code"
        rows = crm_db.execute_query(sql) or []
        defaults = {
            "semantic_type": CategorySemanticType.COMMERCIAL_CATEGORY.value,
            "lifecycle_state": CategoryLifecycleState.ACTIVE.value,
            "searchability_mode": SearchabilityMode.DIRECT_SEARCHABLE.value,
            "legacy_compat_role": None,
        }
        out: List[Dict[str, Any]] = []
        for r in rows:
            item = _row_dict(r)
            item.update(defaults)
            out.append(item)
        return out


def load_legacy_compat_map(crm_db) -> Dict[str, Dict[str, Any]]:
    rows = crm_db.execute_query(
        """
        SELECT legacy_category_code, commercial_category_code, commercial_subcategory_code,
               material_family_code, object_context_code, application_area_code,
               work_method_codes, compat_strategy, notes, registry_version
        FROM crm_category_legacy_compat
        ORDER BY legacy_category_code
        """
    ) or []
    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        item = _row_dict(row)
        codes = item.get("work_method_codes")
        if isinstance(codes, str):
            try:
                item["work_method_codes"] = json.loads(codes)
            except Exception:
                item["work_method_codes"] = []
        result[str(item["legacy_category_code"])] = item
    return result


def load_taxonomy_dimensions(crm_db, *, active_only: bool = True) -> List[Dict[str, Any]]:
    where = "WHERE is_active = TRUE" if active_only else ""
    rows = crm_db.execute_query(
        f"""
        SELECT dimension_type, dimension_code, display_name, normalized_term,
               term_semantic_type, evidence_role, registry_version
        FROM crm_taxonomy_dimensions
        {where}
        ORDER BY dimension_type, dimension_code
        """
    ) or []
    return [_row_dict(r) for r in rows]


def load_signal_examples(crm_db) -> List[Dict[str, Any]]:
    rows = crm_db.execute_query(
        """
        SELECT example_term, normalized_term, term_semantic_type, evidence_role,
               dimension_type, dimension_code, commercial_category_code,
               commercial_subcategory_code, is_commercial_category, notes
        FROM crm_taxonomy_signal_examples
        ORDER BY id
        """
    ) or []
    return [_row_dict(r) for r in rows]


def build_dynamic_registry_snapshot(crm_db) -> Dict[str, Any]:
    """Full registry snapshot for future dynamic consumers."""
    commercial = load_active_commercial_categories(crm_db)
    version_info = get_current_registry_version(crm_db)
    return {
        "registry_version": version_info.get("version", 1),
        "registry_hash": version_info.get("hash") or compute_registry_hash(commercial),
        "commercial_categories": commercial,
        "legacy_compat": load_legacy_compat_map(crm_db),
        "dimensions": load_taxonomy_dimensions(crm_db),
        "signal_examples": load_signal_examples(crm_db),
    }


def classify_signal(
    term: str,
    *,
    dimensions: List[Dict[str, Any]],
    signal_examples: List[Dict[str, Any]],
) -> Optional[SignalClassification]:
    """Classify a normalized signal against taxonomy dimensions/examples."""
    normalized = normalize_term(term)
    if not normalized:
        return None

    for example in signal_examples:
        if normalize_term(example.get("example_term", "")) == normalized or example.get("normalized_term") == normalized:
            return SignalClassification(
                normalized_term=normalized,
                term_semantic_type=TermSemanticType(example["term_semantic_type"]),
                evidence_role=EvidenceRole(example["evidence_role"]),
                dimension_type=DimensionType(example["dimension_type"]) if example.get("dimension_type") else None,
                dimension_code=example.get("dimension_code"),
                is_commercial_category=bool(example.get("is_commercial_category")),
                commercial_category_code=example.get("commercial_category_code"),
                commercial_subcategory_code=example.get("commercial_subcategory_code"),
            )

    for dim in dimensions:
        if dim.get("normalized_term") == normalized:
            return SignalClassification(
                normalized_term=normalized,
                term_semantic_type=TermSemanticType(dim["term_semantic_type"]),
                evidence_role=EvidenceRole(dim["evidence_role"]),
                dimension_type=DimensionType(dim["dimension_type"]),
                dimension_code=dim.get("dimension_code"),
                is_commercial_category=False,
            )

    return None


def validate_category_lifecycle(category: Dict[str, Any]) -> List[str]:
    """Return validation errors for category lifecycle/searchability invariants."""
    errors: List[str] = []
    code = category.get("category_code", "")
    if not is_valid_commercial_category_code(code):
        errors.append(f"invalid commercial category code: {code!r}")

    lifecycle = category.get("lifecycle_state", CategoryLifecycleState.ACTIVE)
    searchability = category.get("searchability_mode", SearchabilityMode.DIRECT_SEARCHABLE)
    semantic = category.get("semantic_type", CategorySemanticType.COMMERCIAL_CATEGORY)

    if semantic in (CategorySemanticType.CONTEXT_ONLY, CategorySemanticType.MATERIAL_ONLY):
        if searchability == SearchabilityMode.DIRECT_SEARCHABLE:
            errors.append(f"{code}: context/material-only category must not be DIRECT_SEARCHABLE")

    if lifecycle == CategoryLifecycleState.ACTIVE and searchability == SearchabilityMode.DIRECT_SEARCHABLE:
        # zero-term searchable ACTIVE commercial categories are a policy violation;
        # enforcement deferred to matcher stage, but flag here for registry QA.
        pass

    return errors
