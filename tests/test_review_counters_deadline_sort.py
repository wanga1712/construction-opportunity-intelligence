from pathlib import Path

from src.services.annotation_state_service import (
    NOT_INTERESTING,
    PROFILED,
    REVIEWED,
    UNREVIEWED,
    annotation_state_counts,
    load_current_annotation_states,
)
from src.services.commercial_routing_v3.submission_window import MIN_REMAINING_SUBMISSION_DAYS
from src.ui.components.analytics_v2.tabs import (
    FARTHEST_DEADLINE_FIRST,
    NEAREST_DEADLINE_FIRST,
    torgi_deadline_order_by,
)
from src.ui.components.analytics_v2.stage_workspace import filtered_review_ids


class StateDb:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute_query(self, _sql, _params):
        self.calls += 1
        return self.rows


def _row(pid, payload):
    return {"id": pid, "procurement_id": pid, "annotation_version": 1,
            "created_at": "now", "payload": payload}


def test_unreviewed_profiled_and_out_of_profile_are_projected_independently():
    db = StateDb([
        _row(2, {"expert_commercial_verdict": "ACTIONABLE"}),
        _row(3, {"expert_scope_verdict": "OUT_OF_PROFILE"}),
        _row(4, {"expert_medal": "NCE"}),
    ])
    states = load_current_annotation_states([1, 2, 3, 4], db)
    counts = annotation_state_counts(states)
    assert db.calls == 1
    assert counts == {
        "ALL": 4, UNREVIEWED: 1, REVIEWED: 3, NOT_INTERESTING: 2,
        PROFILED: 1, "UNANNOTATED": 1, "ANNOTATED": 3,
    }
    assert counts["ALL"] == counts[UNREVIEWED] + counts[REVIEWED]
    assert counts[NOT_INTERESTING] <= counts[REVIEWED]


def test_successful_no_save_counter_transition():
    before = annotation_state_counts(load_current_annotation_states([1], StateDb([])))
    after = annotation_state_counts(load_current_annotation_states(
        [1], StateDb([_row(1, {"expert_scope_verdict": "OUT_OF_PROFILE"})])
    ))
    assert (before[UNREVIEWED], before[REVIEWED], before[NOT_INTERESTING]) == (1, 0, 0)
    assert (after[UNREVIEWED], after[REVIEWED], after[NOT_INTERESTING]) == (0, 1, 1)


def test_review_filters_compose_before_sql_pagination():
    states = load_current_annotation_states(
        [1, 2, 3],
        StateDb([_row(2, {"expert_commercial_verdict": "ACTIONABLE"}),
                 _row(3, {"expert_scope_verdict": "OUT_OF_PROFILE"})]),
    )
    assert filtered_review_ids(states, UNREVIEWED) == [1]
    assert filtered_review_ids(states, REVIEWED) == [2, 3]
    assert filtered_review_ids(states, NOT_INTERESTING) == [3]


def test_deadline_order_sql_defaults_far_and_near_is_selectable():
    far = torgi_deadline_order_by(FARTHEST_DEADLINE_FIRST)
    near = torgi_deadline_order_by(NEAREST_DEADLINE_FIRST)
    assert far == "cp.end_date DESC NULLS LAST, cp.initial_price DESC NULLS LAST, cp.id DESC"
    assert near == "cp.end_date ASC NULLS LAST, cp.initial_price DESC NULLS LAST, cp.id DESC"


def test_sort_is_stable_and_applied_in_sql_before_pagination():
    source = Path("src/ui/components/analytics_v2/tabs.py").read_text(encoding="utf-8")
    loader = source.split("def _load_torgi", 1)[1].split("def _load_queue_statuses_batch", 1)[0]
    assert loader.index("ORDER BY {order_by}") < loader.index("LIMIT %(limit)s OFFSET %(offset)s")
    assert "cp.initial_price DESC NULLS LAST, cp.id DESC" in source
    render = source.split("def _render_torgi_tab", 1)[1].split("# ─── Комиссия", 1)[0]
    assert "sorted(" not in render


def test_save_next_flags_are_set_only_after_authoritative_save_and_before_rerun():
    source = Path("src/ui/components/analytics_v2/annotation_card.py").read_text(encoding="utf-8")
    persist = source.split("def _persist(", 1)[1]
    save_at = persist.index("save_expert_annotation(")
    next_at = persist.index("st.session_state[GO_NEXT_KEY] = True")
    rerun_at = persist.index("st.rerun()")
    assert save_at < next_at < rerun_at
    assert "load_current_annotation_states" not in persist  # no stale local/session counter authority


def test_all_current_card_save_actions_converge_on_authoritative_persist():
    card = Path("src/ui/components/analytics_v2/annotation_card.py").read_text(encoding="utf-8")
    for key in (
        "scope_no_save_next", "guided_save", "guided_save_next",
        "wb_save", "wb_save_next", "wb_oop",
    ):
        assert key in card
    assert card.count("_persist(procurement_id, payload") >= 5
    legacy = Path("src/ui/components/analytics_v2/card_tabs_ai.py").read_text(encoding="utf-8")
    handler = legacy.split("def _handle_save", 1)[1].split("# ─", 1)[0]
    assert handler.index("save_expert_annotation(") < handler.index('st.session_state["annotation_go_next"] = True')


def test_counter_projection_is_uncached_and_rerun_reloads_it():
    service = Path("src/services/annotation_state_service.py").read_text(encoding="utf-8")
    workspace = Path("src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
    assert "@st.cache" not in service
    assert workspace.count("load_current_annotation_states(all_ids, crm_db)") == 1


def test_submission_window_authority_remains_two_days():
    assert MIN_REMAINING_SUBMISSION_DAYS == 2
