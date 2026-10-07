"""Unit tests for approved exact-title rules (no DB, no Qwen)."""
from __future__ import annotations

from src.services.product_subcategory_resolver import (
    SOURCE_APPROVED_TITLE_RULE,
    ResolverContext,
    ResolverInput,
    is_unclassified,
    resolve,
)
from src.services.procurement_title_normalizer import (
    normalize_procurement_title_v1,
)
from src.services.procurement_title_rule_service import (
    lookup_exact_title_rule,
    resolver_rules_from,
)


def _assign_rule(**over):
    row = {
        "id": 1,
        "action": "ASSIGN_SUBCATEGORY",
        "target_category_code": "computers",
        "target_subcategory_code": "desktop_computers",
        "confidence": 0.99,
        "execution_enabled": True,
        "reason": "test",
    }
    row.update(over)
    return row


def _lookup(title, category):
    return lookup_exact_title_rule(
        title, category, {("computers", "поставка системного блока"): _assign_rule()}
    )


def test_normalization_is_conservative():
    assert normalize_procurement_title_v1("Поставка серверов.") == "поставка серверов"
    # digits / units are preserved, never merged
    assert normalize_procurement_title_v1("Сервер 2U") == "сервер 2u"
    assert normalize_procurement_title_v1("220 кВ") != normalize_procurement_title_v1("110 кв")


def test_same_title_correct_category_matches():
    res = _lookup("Поставка системного блока.", "computers")
    assert res["matched"] is True
    assert res["action"] == "ASSIGN_SUBCATEGORY"


def test_same_title_other_category_no_match():
    assert _lookup("Поставка системного блока", "lighting")["matched"] is False


def test_assign_subcategory_returns_target():
    ctx = ResolverContext(
        product_by_category={"computers": {"desktop_computers"}},
        approved_title_rules=resolver_rules_from(
            {("computers", "поставка системного блока"): _assign_rule()}
        ),
    )
    res = resolve(ResolverInput(category_code="computers", title="Поставка системного блока"),
                  ctx)
    assert res.subcategory_code == "desktop_computers"
    assert res.source == SOURCE_APPROVED_TITLE_RULE
    assert res.confidence == 0.99


def test_remove_category_not_executable():
    # A REMOVE_CATEGORY knowledge rule must never reach the resolver.
    remove_rule = _assign_rule(action="REMOVE_CATEGORY", execution_enabled=False,
                               target_subcategory_code=None)
    rules = {("lighting", "капитальный ремонт"): remove_rule}
    assert resolver_rules_from(rules) == {}
    ctx = ResolverContext(product_by_category={"lighting": {"street_luminaires"}},
                          approved_title_rules=resolver_rules_from(rules))
    res = resolve(ResolverInput(category_code="lighting", title="капитальный ремонт"), ctx)
    assert res.subcategory_code is None


def test_existing_non_null_subcategory_not_overwritten():
    # The backfill guard only touches unclassified rows.
    assert is_unclassified(None) is True
    assert is_unclassified("") is True
    assert is_unclassified("SUBCATEGORY_NOT_ASSIGNED") is True
    assert is_unclassified("monitors") is False
