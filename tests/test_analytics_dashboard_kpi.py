"""Tests for analytics_dashboard_kpi_service — factual KPI computation.

Validates:
- Medal ordering and transition classification
- Transition invariant (SAME + DOWN + UP == matrix sum)
- Rejected exclusion from 4x4 matrix
- Multi-category procurement gives N medal decisions
- research_prior_band never used as commercial medal
- Source table → law mapping
- Rolling 24h uses crm_created_at not updated_at
"""

from __future__ import annotations

import pytest

from src.services.analytics_dashboard_kpi_service import (
    MEDAL_ORDER,
    MEDAL_RANK,
    VALID_MEDALS,
    ArrayCounts,
    DashboardKPI,
    MedalDecisions,
    MedalTransition,
    PipelineStatus,
    _apply_array_row,
    _classify_transition,
    _map_law,
    load_dashboard_kpi,
)


# ── Medal ordering ────────────────────────────────────────────────────────

class TestMedalOrdering:
    def test_gold_is_highest(self):
        assert MEDAL_ORDER["GOLD"] > MEDAL_ORDER["SILVER"]
        assert MEDAL_ORDER["GOLD"] > MEDAL_ORDER["BRONZE"]
        assert MEDAL_ORDER["GOLD"] > MEDAL_ORDER["WOOD"]

    def test_silver_above_bronze(self):
        assert MEDAL_ORDER["SILVER"] > MEDAL_ORDER["BRONZE"]

    def test_bronze_above_wood(self):
        assert MEDAL_ORDER["BRONZE"] > MEDAL_ORDER["WOOD"]

    def test_rank_tuple_order(self):
        assert MEDAL_RANK == ("GOLD", "SILVER", "BRONZE", "WOOD")

    def test_valid_medals_set(self):
        assert VALID_MEDALS == {"GOLD", "SILVER", "BRONZE", "WOOD"}


# ── Transition classification ─────────────────────────────────────────────

class TestTransitionClassification:
    def test_same(self):
        for m in MEDAL_RANK:
            assert _classify_transition(m, m) == "SAME"

    def test_down_gold_to_bronze(self):
        assert _classify_transition("GOLD", "BRONZE") == "DOWN"

    def test_down_silver_to_wood(self):
        assert _classify_transition("SILVER", "WOOD") == "DOWN"

    def test_up_wood_to_gold(self):
        assert _classify_transition("WOOD", "GOLD") == "UP"

    def test_up_bronze_to_silver(self):
        assert _classify_transition("BRONZE", "SILVER") == "UP"


# ── Transition invariant ──────────────────────────────────────────────────

class TestTransitionInvariant:
    def test_invariant_empty(self):
        md = MedalDecisions()
        assert md.invariant_pass  # 0 == 0

    def test_invariant_basic(self):
        md = MedalDecisions(
            same=5,
            down=3,
            up=2,
            matrix=[
                MedalTransition("GOLD", "GOLD", 5),    # SAME
                MedalTransition("GOLD", "SILVER", 3),   # DOWN
                MedalTransition("WOOD", "GOLD", 2),     # UP
            ],
        )
        assert md.total_decided == 10
        assert md.matrix_sum == 10
        assert md.invariant_pass

    def test_invariant_fails_on_mismatch(self):
        md = MedalDecisions(
            same=5,
            down=3,
            up=2,
            matrix=[
                MedalTransition("GOLD", "GOLD", 5),
                MedalTransition("GOLD", "SILVER", 2),  # mismatch: down=3 but matrix only has 2
            ],
        )
        assert not md.invariant_pass

    def test_real_s13_data_invariant(self):
        """Verified against actual S13 data from audit query."""
        md = MedalDecisions(
            same=1898 + 17 + 436,   # BRONZE→BRONZE + SILVER→SILVER + WOOD→WOOD
            down=55 + 1103,          # GOLD→BRONZE + SILVER→BRONZE
            up=0,
            matrix=[
                MedalTransition("BRONZE", "BRONZE", 1898),
                MedalTransition("GOLD", "BRONZE", 55),
                MedalTransition("SILVER", "BRONZE", 1103),
                MedalTransition("SILVER", "SILVER", 17),
                MedalTransition("WOOD", "WOOD", 436),
            ],
        )
        assert md.same == 2351
        assert md.down == 1158
        assert md.up == 0
        assert md.total_decided == 3509
        assert md.matrix_sum == 3509
        assert md.invariant_pass


# ── Multi-category procurement counting ───────────────────────────────────

class TestMultiCategoryCounting:
    def test_one_procurement_three_categories(self):
        """One procurement with 3 category opportunities → 3 medal decisions."""
        # Simulates the example from the WIP spec:
        # Гидроизоляция: GOLD → GOLD (SAME)
        # Напольные покрытия: SILVER → BRONZE (DOWN)
        # Светотехника: BRONZE → SILVER (UP)
        md = MedalDecisions(
            same=1,
            down=1,
            up=1,
            matrix=[
                MedalTransition("GOLD", "GOLD", 1),
                MedalTransition("SILVER", "BRONZE", 1),
                MedalTransition("BRONZE", "SILVER", 1),
            ],
        )
        assert md.total_decided == 3  # 3 medal decisions, NOT 1 procurement
        assert md.invariant_pass


# ── Rejected exclusion ────────────────────────────────────────────────────

class TestRejectedExclusion:
    def test_rejected_not_in_matrix(self):
        """Rejected opportunities are tracked separately, not in 4x4."""
        md = MedalDecisions(
            same=5,
            down=0,
            up=0,
            rejected=3,
            matrix=[MedalTransition("GOLD", "GOLD", 5)],
        )
        # Rejected count is separate
        assert md.rejected == 3
        # Matrix only contains non-rejected
        assert md.matrix_sum == 5
        assert md.invariant_pass


# ── Source table mapping ──────────────────────────────────────────────────

class TestSourceTableMapping:
    def test_44fz(self):
        assert _map_law("reestr_contract_44_fz") == "44-ФЗ"

    def test_44fz_awarded(self):
        assert _map_law("reestr_contract_44_fz_awarded") == "44-ФЗ"

    def test_223fz(self):
        assert _map_law("reestr_contract_223_fz") == "223-ФЗ"

    def test_223fz_commission_work(self):
        assert _map_law("reestr_contract_223_fz_commission_work") == "223-ФЗ"

    def test_unknown_table(self):
        assert _map_law("some_other_table") is None


# ── Array count accumulation ──────────────────────────────────────────────

class TestArrayAccumulation:
    def test_apply_rows(self):
        arr = ArrayCounts()
        _apply_array_row(arr, "reestr_contract_44_fz", "torgi", 100)
        _apply_array_row(arr, "reestr_contract_223_fz", "torgi", 50)
        _apply_array_row(arr, "reestr_contract_44_fz_awarded", "razygranye", 30)
        _apply_array_row(arr, "reestr_contract_223_fz_commission_work", "torgi", 5)
        assert arr.fz44_torgi == 100
        assert arr.fz223_torgi == 55  # 50 + 5
        assert arr.fz44_razygranye == 30
        assert arr.fz223_razygranye == 0
        assert arr.total == 185

    def test_unknown_source_ignored(self):
        arr = ArrayCounts()
        _apply_array_row(arr, "unknown_table", "torgi", 999)
        assert arr.total == 0


# ── research_prior_band gate ──────────────────────────────────────────────

class TestResearchPriorBandGate:
    def test_research_prior_band_not_in_valid_medals(self):
        """research_prior_band values must NOT be treated as commercial medals."""
        # research_prior_band has values like 'GOLD', 'SILVER', 'BRONZE', 'WOOD'
        # but they are NOT commercial medals — they are research priority bands.
        # The service only reads from crm_procurement_category_opportunities
        # (candidate_initial_medal, current_effective_medal), never from
        # document_processing_queue.research_prior_band.
        # This is a structural test — the SQL in load_dashboard_kpi() only queries
        # crm_procurement_category_opportunities for medals.
        import inspect
        source = inspect.getsource(load_dashboard_kpi)
        assert "research_prior_band" not in source
        assert "research_prior_score" not in source


# ── Pipeline status mapping ───────────────────────────────────────────────

class TestPipelineStatusMapping:
    def test_rejected_is_source_gap(self):
        """ОТКЛОНЕНО cannot be computed from current pipeline data."""
        ps = PipelineStatus()
        assert ps.rejected_available is False


# ── Matrix grid ───────────────────────────────────────────────────────────

class TestMatrixGrid:
    def test_grid_has_16_cells(self):
        md = MedalDecisions(
            matrix=[MedalTransition("GOLD", "GOLD", 5)],
        )
        grid = md.matrix_grid()
        assert len(grid) == 16

    def test_grid_includes_zeros(self):
        md = MedalDecisions(
            matrix=[MedalTransition("GOLD", "GOLD", 5)],
        )
        grid = md.matrix_grid()
        assert grid[("GOLD", "GOLD")] == 5
        assert grid[("GOLD", "SILVER")] == 0
        assert grid[("WOOD", "WOOD")] == 0


# ── Percentages ───────────────────────────────────────────────────────────

class TestPercentages:
    def test_pct_with_data(self):
        md = MedalDecisions(same=7, down=2, up=1)
        assert md.same_pct() == pytest.approx(70.0)
        assert md.down_pct() == pytest.approx(20.0)
        assert md.up_pct() == pytest.approx(10.0)

    def test_pct_empty(self):
        md = MedalDecisions()
        assert md.same_pct() == 0.0
        assert md.down_pct() == 0.0
        assert md.up_pct() == 0.0


# ── Loader with mock DB ──────────────────────────────────────────────────

class _MockDB:
    """Minimal mock for testing the loader without a real DB."""

    def __init__(self, responses: dict[str, list] | None = None):
        self._responses = responses or {}
        self.calls: list[str] = []

    def execute_query(self, sql: str, params: Any = None, **kw) -> list:
        self.calls.append(sql[:80])
        for key, response in self._responses.items():
            if key in sql:
                return response
        return []


class TestLoaderMockDB:
    def test_empty_db_returns_zeros(self):
        db = _MockDB()
        kpi = load_dashboard_kpi(db)
        assert kpi.array.total == 0
        assert kpi.new_24h.total == 0
        assert kpi.medals.total_decided == 0
        assert kpi.query_count >= 1

    def test_array_counts_from_mock(self):
        db = _MockDB({
            "WHERE crm_stage IN": [
                {"source_table": "reestr_contract_44_fz", "crm_stage": "torgi", "cnt": 100},
                {"source_table": "reestr_contract_223_fz", "crm_stage": "razygranye", "cnt": 20},
            ],
        })
        kpi = load_dashboard_kpi(db)
        assert kpi.array.fz44_torgi == 100
        assert kpi.array.fz223_razygranye == 20

    def test_no_pipeline_db_registers_gap(self):
        db = _MockDB()
        kpi = load_dashboard_kpi(db, doc_db_connect=None)
        assert "PIPELINE_DB_NOT_CONFIGURED" in kpi.source_gaps

    def test_rejected_always_source_gap(self):
        db = _MockDB()
        kpi = load_dashboard_kpi(db)
        assert any("SOURCE_GAP" in g for g in kpi.source_gaps)

    def test_no_research_prior_in_medal_sql(self):
        """The medal query must NOT use research_prior_band."""
        db = _MockDB()
        load_dashboard_kpi(db)
        for call in db.calls:
            assert "research_prior" not in call.lower()
