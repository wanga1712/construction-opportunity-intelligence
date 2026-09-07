from src.learning.procurement_scope.classifier import ProcurementScopeClassifierV1, ProcurementScopeType
from src.services.procurement_research_admission import (
    ADMISSION_POLICY_VERSION,
    evaluate_admission,
)
from src.services.procurement_scope_authority import classify_procurement, materialize_scope_authority


def test_scope_is_pre_research_and_fail_closed_for_okpd_only():
    result = ProcurementScopeClassifierV1().classify_procurement({"title": "", "okpd_codes": ["22.23.11.000"]})
    assert result["procurement_scope_type"] == ProcurementScopeType.UNKNOWN.value
    assert result["scope_evidence"]["post_research_feature_count"] == 0


def test_unknown_reason_is_diagnostic_but_remains_fail_closed():
    classifier = ProcurementScopeClassifierV1()
    assert classifier.classify_procurement({"title": "Ремонт дороги", "okpd_codes": []})[
        "scope_evidence"
    ]["rule_id"].endswith("unsupported_pre_research_pattern")
    assert classifier.classify_procurement({"title": "", "okpd_codes": []})[
        "scope_evidence"
    ]["rule_id"].endswith("missing_title_or_subject")
    assert classifier.classify_procurement({"title": "Ремонт дороги", "okpd_codes": []})[
        "procurement_scope_type"
    ] == ProcurementScopeType.UNKNOWN.value


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
    assert authority.scope_evidence["rule_id"]
    assert authority.scope_evidence["okpd_codes_used"] == ["22.23.11.000"]
    assert authority.admission_policy_version == ADMISSION_POLICY_VERSION
    assert authority.scope_evaluated_at is not None
    assert authority.admission_evaluated_at is not None


def test_admission_matrix_and_waiting_award():
    cases = [
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "DIRECT_GOODS", "ELIGIBLE"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "DIRECT_GOODS", "EXCLUDED"),
        ({"crm_stage": "torgi", "award_status": "submission_closed_waiting_award"}, "DIRECT_GOODS", "HOLD"),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "WORKS_WITH_EMBEDDED_PRODUCTS", "ELIGIBLE"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "WORKS_WITH_EMBEDDED_PRODUCTS", "ELIGIBLE"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "DESIGN_PROJECT", "ELIGIBLE"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "EQUIPMENT_AND_INSTALLATION", "HOLD"),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "PURE_SERVICE", "HOLD"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "PURE_SERVICE", "HOLD"),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "SERVICE_WITH_CONSUMABLES", "HOLD"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "MIXED", "HOLD"),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "UNKNOWN", "HOLD"),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "UNKNOWN", "HOLD"),
        ({"crm_stage": "cancelled", "award_status": "cancelled"}, "DIRECT_GOODS", "EXCLUDED"),
        ({"crm_stage": "cancelled", "award_status": "cancelled"}, "WORKS_WITH_EMBEDDED_PRODUCTS", "EXCLUDED"),
    ]
    for procurement, scope, expected in cases:
        assert evaluate_admission(procurement, scope).state == expected


def test_lifecycle_transitions_are_admission_reactive():
    works = "WORKS_WITH_EMBEDDED_PRODUCTS"
    goods = "DIRECT_GOODS"
    assert evaluate_admission(
        {"crm_stage": "torgi", "award_status": "submission_closed_waiting_award"}, works
    ).reason == "WAITING_FOR_AWARD"
    assert evaluate_admission({"crm_stage": "razygranye", "award_status": "awarded"}, works).state == "ELIGIBLE"
    assert evaluate_admission(
        {"crm_stage": "torgi", "award_status": "submission_closed_waiting_award"}, goods
    ).state == "HOLD"
    assert evaluate_admission({"crm_stage": "razygranye", "award_status": "awarded"}, goods).reason == "AWARDED_DIRECT_GOODS"


def test_gold_never_resurrects_excluded_or_hold_scope():
    assert evaluate_admission(
        {"crm_stage": "razygranye", "award_status": "awarded", "research_prior_band": "GOLD"},
        "DIRECT_GOODS",
    ).state == "EXCLUDED"
    assert evaluate_admission(
        {"crm_stage": "torgi", "award_status": "submission_open", "research_prior_effective_band": "GOLD"},
        "UNKNOWN",
    ).state == "HOLD"


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


def test_materializer_sql_is_idempotent_and_policy_versioned():
    class Cursor:
        def __init__(self):
            self.sql = []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, _params):
            self.sql.append(sql)

    class Connection:
        def __init__(self):
            self.cursor_obj = Cursor()
            self.commits = 0

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.commits += 1

    connection = Connection()
    row = {
        "id": 17,
        "auction_name": "Поставка линолеума",
        "okpd_codes": ["22.23.11.000"],
        "crm_stage": "torgi",
        "award_status": "submission_open",
    }
    result = materialize_scope_authority(connection, [row], write=True)
    assert result == {"classified": 1, "materialized": 1}
    assert connection.commits == 1
    assert "ON CONFLICT (procurement_id) DO UPDATE" in connection.cursor_obj.sql[0]
    assert "admission_policy_version" in connection.cursor_obj.sql[0]
    assert "admission_evaluated_at" in connection.cursor_obj.sql[0]
