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


# --- TAXONOMY GAPS V1: upgraded KEEP -> ASSIGN_SUBCATEGORY rules ---------------
def _gap_resolve(category, title, normalized_key, subcategory):
    rule = {
        "id": 99, "action": "ASSIGN_SUBCATEGORY", "target_category_code": category,
        "target_subcategory_code": subcategory, "confidence": 0.99,
        "execution_enabled": True, "reason": "taxonomy_gap_v1",
    }
    ctx = ResolverContext(
        product_by_category={category: {subcategory}},
        approved_title_rules=resolver_rules_from({(category, normalized_key): rule}),
    )
    return resolve(ResolverInput(category_code=category, title=title), ctx)


def test_gap_printing_consumables():
    res = _gap_resolve("computers", "Поставка картриджей.", "поставка картриджей",
                       "printing_consumables")
    assert res.subcategory_code == "printing_consumables"
    assert res.source == SOURCE_APPROVED_TITLE_RULE


def test_gap_projectors():
    res = _gap_resolve("computers", "Проектор", "проектор", "projectors")
    assert res.subcategory_code == "projectors"


def test_gap_generic_luminaires():
    res = _gap_resolve("lighting", "Поставка светильников", "поставка светильников",
                       "generic_luminaires")
    assert res.subcategory_code == "generic_luminaires"


def test_gap_led_lamps():
    res = _gap_resolve("lighting", "Лампа светодиодная", "лампа светодиодная", "led_lamps")
    assert res.subcategory_code == "led_lamps"


def test_gap_culvert_pipes():
    res = _gap_resolve("drainage_water_management", "Водопропускная труба",
                       "водопропускная труба", "culvert_pipes")
    assert res.subcategory_code == "culvert_pipes"
