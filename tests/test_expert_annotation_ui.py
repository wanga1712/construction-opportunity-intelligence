from pathlib import Path

from src.services.expert_annotation_service import save_expert_annotation
from src.ui.components.analytics_v2 import card_tabs_ai
from src.ui.components.analytics_v2.card_tabs_ai_expert_form import (
    _ERROR_REASONS,
    _HYPOTHESIS_REASONS,
    _MEDAL_REASONS,
    _assemble_payload,
    _build_correct_payload,
)


def _payload(verdict: str) -> dict:
    return _assemble_payload(
        assessment={"id": 42},
        expert_verdict=verdict,
        expert_form="CONSTRUCTION_WORKS",
        expert_obj_type="школа",
        expert_obj_subtype="общеобразовательная",
        expert_work_stage="капремонт",
        expert_commercial_verdict="ACTIONABLE",
        expert_medal="SILVER",
        medal_reason="HIGH_COMMERCIAL_FIT",
        medal_comment="",
        error_reasons=[],
        expert_comment="",
        opps=[{"expert_rank": 1}],
        rejected=[],
        proposals=[],
        created_by="tester",
    )


def test_full_form_preserves_explicit_expert_verdict() -> None:
    assert _payload("PARTIALLY_CORRECT")["expert_verdict"] == "PARTIALLY_CORRECT"
    assert _payload("WRONG")["expert_verdict"] == "WRONG"


def test_model_object_type_is_not_merged_into_expert_suggestions() -> None:
    source = Path(
        "src/ui/components/analytics_v2/card_tabs_ai_expert_form.py"
    ).read_text(encoding="utf-8")
    suggestion_block = source.split(
        "# Suggestions are human-authored values only.", 1
    )[1].split("expert_obj_type = st.text_input", 1)[0]
    assert 'nr.get("object_type")' not in suggestion_block
    assert "set(expert_object_types)" in suggestion_block


def test_correct_payload_persists_explicit_expert_form() -> None:
    payload = _build_correct_payload(
        {"id": 7, "normalized_result": {"procurement_form": "DESIGN_ONLY"}},
        "CONSTRUCTION_WORKS",
        "ok",
        "tester",
    )
    assert payload["expert_procurement_form"] == "CONSTRUCTION_WORKS"


def test_training_reason_contracts_are_available() -> None:
    error_codes = {code for code, _ in _ERROR_REASONS}
    addition_codes = {code for code, _ in _HYPOTHESIS_REASONS}
    medal_codes = {code for code, _ in _MEDAL_REASONS}
    assert {
        "WRONG_PROCUREMENT_SUBJECT", "CONTEXT_AS_PRODUCT",
        "ACCESSORY_AS_PRIMARY_PRODUCT", "OUTSIDE_SELLABLE_REGISTRY",
    } <= error_codes
    assert {
        "DIRECT_TITLE_EVIDENCE", "EXPECTED_IN_PROJECT_DOCUMENTATION",
        "EXPERT_COMMERCIAL_KNOWLEDGE",
    } <= addition_codes
    assert {"INSUFFICIENT_TIME", "COMMERCIAL_WINDOW_CLOSED"} <= medal_codes


class _FakeCursor:
    def __init__(self, dict_rows: bool = False) -> None:
        self.calls: list[tuple[str, tuple | None]] = []
        self._fetches = (
            [{"next_version": 1}, {"id": 99}]
            if dict_rows else [(1,), (99,)]
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None) -> None:
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._fetches.pop(0)


class _FakeConnection:
    def __init__(self, dict_rows: bool = False) -> None:
        self.cur = _FakeCursor(dict_rows=dict_rows)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cur


class _ProductionStyleDb:
    def __init__(self, dict_rows: bool = False) -> None:
        self._connection = _FakeConnection(dict_rows=dict_rows)
        self.ensured = False

    def _ensure_connection(self) -> None:
        self.ensured = True


def test_save_supports_production_singleton_db_manager() -> None:
    db = _ProductionStyleDb(dict_rows=True)
    annotation_id = save_expert_annotation(123, {"expert_verdict": "WRONG"}, "tester", db)
    assert annotation_id == 99
    assert db.ensured is True
    sql_calls = [sql for sql, _ in db._connection.cur.calls]
    assert sql_calls[0].startswith("SELECT pg_advisory_xact_lock")
    assert any("INSERT INTO crm_v3_expert_annotations" in sql for sql in sql_calls)


class _FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = {"ann_55_draft_init": True}
        self.rerun_called = False

    def success(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def error(self, *_args, **_kwargs) -> None:
        raise AssertionError("unexpected UI error")

    def rerun(self) -> None:
        self.rerun_called = True


def test_save_next_sets_navigation_flag(monkeypatch) -> None:
    fake_st = _FakeStreamlit()
    audit_calls = []
    monkeypatch.setattr(card_tabs_ai, "st", fake_st)
    monkeypatch.setattr(card_tabs_ai, "save_expert_annotation", lambda **_kwargs: 123)
    monkeypatch.setattr(
        card_tabs_ai,
        "write_audit_row",
        lambda **kwargs: audit_calls.append(kwargs),
    )
    card_tabs_ai._handle_save(
        procurement_id=55,
        payload={"expert_verdict": "CORRECT", "taxonomy_proposals": []},
        assessment={"normalized_result": {"model": "immutable"}},
        created_by="tester",
        crm_db=object(),
        save_and_next=True,
    )
    assert fake_st.session_state["annotation_go_next"] is True
    assert "ann_55_draft_init" not in fake_st.session_state
    assert fake_st.rerun_called is True
    assert audit_calls[0]["model_raw"] == {"model": "immutable"}
