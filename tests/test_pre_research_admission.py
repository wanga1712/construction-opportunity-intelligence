from src.learning.procurement_scope.classifier import ProcurementScopeClassifierV1, ProcurementScopeType
from src.services.procurement_research_admission import evaluate_admission
from src.services.procurement_scope_authority import classify_procurement, materialize_scope_authority


def test_scope_is_pre_research_and_fail_closed_for_okpd_only():
    result = ProcurementScopeClassifierV1().classify_procurement({"title": "", "okpd_codes": ["22.23.11.000"]})
    assert result["procurement_scope_type"] == ProcurementScopeType.UNKNOWN.value
    assert result["scope_evidence"]["post_research_feature_count"] == 0


def test_regression_awarded_direct_goods_is_excluded():
    procurement = {
        "id": 2,
        "auction_name": "Линолеум и твердые неполимерные материалы для покрытия пола",
        "okpd_codes": ["22.23.11.000"],
        "crm_stage": "razygranye",
        "award_status": "awarded",
    }
    authority = classify_procurement(procurement)
    assert authority.procurement_scope_type == ProcurementScopeType.DIRECT_GOODS.value
    assert authority.admission_state == "EXCLUDED"
    assert authority.admission_reason == "AWARDED_DIRECT_GOODS"
    assert authority.scope_evidence["post_research_feature_count"] == 0


def test_admission_matrix_and_waiting_award():
    cases = [
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "DIRECT_GOODS", "ELIGIBLE"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "DIRECT_GOODS", "EXCLUDED"),
        ({"crm_stage": "torgi", "award_status": "submission_closed_waiting_award"}, "DIRECT_GOODS", "HOLD"),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "WORKS_WITH_EMBEDDED_PRODUCTS", "ELIGIBLE"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "WORKS_WITH_EMBEDDED_PRODUCTS", "ELIGIBLE"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "DESIGN_PROJECT", "ELIGIBLE"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "EQUIPMENT_AND_INSTALLATION", "ELIGIBLE"),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "PURE_SERVICE", "EXCLUDED"),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "UNKNOWN", "HOLD"),
    ]
    for procurement, scope, expected in cases:
        assert evaluate_admission(procurement, scope).state == expected


def test_materializer_is_read_only_by_default_and_one_authority_per_procurement():
    row = {
        "id": 17,
        "auction_name": "Поставка линолеума",
        "okpd_codes": ["22.23.11.000"],
        "crm_stage": "torgi",
        "award_status": "submission_open",
    }
    result = materialize_scope_authority(None, [row])
    assert result == {"classified": 1, "materialized": 0}
