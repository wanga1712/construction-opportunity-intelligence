"""Approved exact-title rules: deterministic lookup service (no model, no Qwen).

Runtime match key is strictly:

    (normalization_version, normalized_title, current_category_code)

A bare ``title_group_id`` is never used as the runtime key: identical
construction-work titles legitimately appear in several categories at once, so
matching must stay category-scoped and fail-safe.

Only ``is_active = TRUE`` rules are ever returned. Only
``action = ASSIGN_SUBCATEGORY`` with ``execution_enabled = TRUE`` may mutate a
subcategory; KEEP / MOVE_CATEGORY / REMOVE_CATEGORY are knowledge rules and are
returned but never applied here.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from src.services.procurement_title_normalizer import (
    NORMALIZATION_VERSION,
    normalize_procurement_title_v1,
)

ACTION_ASSIGN_SUBCATEGORY = "ASSIGN_SUBCATEGORY"
ACTION_KEEP = "KEEP"
ACTION_MOVE_CATEGORY = "MOVE_CATEGORY"
ACTION_REMOVE_CATEGORY = "REMOVE_CATEGORY"
ALLOWED_ACTIONS = (
    ACTION_ASSIGN_SUBCATEGORY,
    ACTION_KEEP,
    ACTION_MOVE_CATEGORY,
    ACTION_REMOVE_CATEGORY,
)

SOURCE_APPROVED_TITLE_RULE = "APPROVED_TITLE_RULE"

# (current_category_code, normalized_title) -> rule
RuleKey = Tuple[str, str]
# resolver-friendly value: (target_subcategory_code, confidence, reason)
ResolverRule = Tuple[str, float, str]

_COLUMNS = (
    "id, normalization_version, normalized_title, current_category_code, action, "
    "target_category_code, target_subcategory_code, confidence, rule_scope, "
    "rule_level, reason, approved_source, execution_enabled"
)


def rule_key(normalized_title: str, current_category_code: str) -> RuleKey:
    return (current_category_code, normalized_title)


def load_exact_title_rules(
    cur, normalization_version: str = NORMALIZATION_VERSION
) -> Dict[RuleKey, dict]:
    """Load ALL active rules for a normalization version, keyed for lookup."""
    cur.execute(
        f"SELECT {_COLUMNS} FROM crm_procurement_title_rules "
        "WHERE is_active = TRUE AND normalization_version = %s",
        (normalization_version,),
    )
    names = [d[0] for d in cur.description]
    rules: Dict[RuleKey, dict] = {}
    for raw in cur.fetchall():
        row = dict(zip(names, raw))
        rules[rule_key(row["normalized_title"], row["current_category_code"])] = row
    return rules


def resolver_rules_from(rules: Dict[RuleKey, dict]) -> Dict[RuleKey, ResolverRule]:
    """Pure filter: keep only executable ASSIGN_SUBCATEGORY rules.

    KEEP / MOVE_CATEGORY / REMOVE_CATEGORY and non-executable ASSIGN rows are
    knowledge only and are never handed to the resolver.
    """
    out: Dict[RuleKey, ResolverRule] = {}
    for key, row in rules.items():
        if row["action"] != ACTION_ASSIGN_SUBCATEGORY or not row["execution_enabled"]:
            continue
        out[key] = (
            row["target_subcategory_code"],
            float(row["confidence"]),
            row["reason"] or "approved exact title",
        )
    return out


def build_resolver_rules(cur, normalization_version: str = NORMALIZATION_VERSION):
    """Return resolver-ready rules: ASSIGN_SUBCATEGORY + execution_enabled only."""
    return resolver_rules_from(load_exact_title_rules(cur, normalization_version))


def lookup_exact_title_rule(title: str, current_category_code: str, rules: Dict):
    """Pure lookup against a preloaded ``rules`` mapping.

    Returns a dict with ``matched`` plus the rule fields when matched.
    """
    normalized = normalize_procurement_title_v1(title)
    row = rules.get(rule_key(normalized, current_category_code)) if rules else None
    if not row:
        return {"matched": False, "normalized_title": normalized}
    return {
        "matched": True,
        "normalized_title": normalized,
        "rule_id": row.get("id"),
        "action": row.get("action"),
        "target_category_code": row.get("target_category_code"),
        "target_subcategory_code": row.get("target_subcategory_code"),
        "confidence": float(row["confidence"]) if row.get("confidence") is not None else None,
        "execution_enabled": bool(row.get("execution_enabled")),
        "rule_scope": row.get("rule_scope"),
        "reason": row.get("reason"),
    }


def lookup_exact_title_rule_db(
    cur,
    title: str,
    current_category_code: str,
    normalization_version: str = NORMALIZATION_VERSION,
) -> dict:
    """DB-backed lookup (is_active = TRUE only)."""
    normalized = normalize_procurement_title_v1(title)
    cur.execute(
        f"SELECT {_COLUMNS} FROM crm_procurement_title_rules "
        "WHERE is_active = TRUE AND normalization_version = %s "
        "AND current_category_code = %s AND normalized_title = %s",
        (normalization_version, current_category_code, normalized),
    )
    names = [d[0] for d in cur.description]
    raw = cur.fetchone()
    if not raw:
        return {"matched": False, "normalized_title": normalized}
    row = dict(zip(names, raw))
    return {
        "matched": True,
        "normalized_title": normalized,
        "rule_id": row["id"],
        "action": row["action"],
        "target_category_code": row["target_category_code"],
        "target_subcategory_code": row["target_subcategory_code"],
        "confidence": float(row["confidence"]),
        "execution_enabled": bool(row["execution_enabled"]),
        "rule_scope": row["rule_scope"],
        "reason": row["reason"],
    }
