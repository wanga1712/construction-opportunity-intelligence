from pathlib import Path

import pytest

from src.services.annotation_card_view import compose_annotation_card_view
from src.ui.analytics_contour_v2_page import _reset_analytics_filters_state
from src.ui.components.analytics_v2.annotation_queue import (
    ACTIVE_QUEUE_KEY,
    GO_NEXT_FROM_KEY,
    GO_NEXT_KEY,
    bind_and_advance,
)
from src.ui.components.analytics_v2 import stage_workspace


class _Rerun(Exception):
    pass


class _St:
    def __init__(self, session=None, click=None):
        self.session_state = session or {}
        self.click = click

    def button(self, label, **_kwargs):
        return label == self.click

    def rerun(self):
        raise _Rerun()


def _cards(*ids):
    return [{"id": value, "auction_name": f"Card {value}"} for value in ids]


def test_list_route_does_not_load_full_detail_or_documents(monkeypatch):
    fake = _St()
    rendered = []
    monkeypatch.setattr(stage_workspace, "st", fake)
    monkeypatch.setattr(
        stage_workspace,
        "render_stage_list_card",
        lambda card, idx, **kwargs: rendered.append((card["id"], idx, kwargs["stage"])),
    )
    monkeypatch.setattr(
        stage_workspace,
        "_render_selected_detail",
        lambda _pid: pytest.fail("full detail must be lazy"),
    )
    assert stage_workspace.render_stage_workspace(
        _cards(1, 2, 3), session_key="selected_torgi_id", stage="OPEN", stage_label="Идут торги"
    ) == "LIST"
    assert rendered == [(1, 0, "OPEN"), (2, 1, "OPEN"), (3, 2, "OPEN")]


def test_selected_route_renders_one_full_detail(monkeypatch):
    fake = _St({"selected_razygr_id": 20})
    details = []
    monkeypatch.setattr(stage_workspace, "st", fake)
    monkeypatch.setattr(stage_workspace, "_render_selected_detail", details.append)
    assert stage_workspace.render_stage_workspace(
        _cards(10, 20),
        session_key="selected_razygr_id",
        stage="AWARDED",
        stage_label="Разыгранные",
    ) == "DETAIL"
    assert details == [20]
    assert fake.session_state[ACTIVE_QUEUE_KEY] == "selected_razygr_id"


def test_back_clears_only_current_selection_and_preserves_filters(monkeypatch):
    session = {
        "selected_torgi_id": 1,
        "selected_razygr_id": 99,
        "torgi_ai_filter": "IN_PROFILE",
        "torgi_qual_layer": "✓ Подтверждено",
        ACTIVE_QUEUE_KEY: "selected_torgi_id",
    }
    monkeypatch.setattr(stage_workspace, "st", _St(session, "← Назад к списку · Идут торги"))
    with pytest.raises(_Rerun):
        stage_workspace.render_stage_workspace(
            _cards(1, 2), session_key="selected_torgi_id", stage="OPEN", stage_label="Идут торги"
        )
    assert "selected_torgi_id" not in session
    assert ACTIVE_QUEUE_KEY not in session
    assert session["selected_razygr_id"] == 99
    assert session["torgi_ai_filter"] == "IN_PROFILE"
    assert session["torgi_qual_layer"] == "✓ Подтверждено"


def test_save_next_is_consumed_only_by_active_stage_queue():
    session = {
        "selected_komissia_id": 4,
        ACTIVE_QUEUE_KEY: "selected_komissia_id",
        GO_NEXT_KEY: True,
        GO_NEXT_FROM_KEY: 4,
    }
    bind_and_advance(_cards(1, 2), "selected_torgi_id", session)
    assert session[GO_NEXT_KEY] is True
    bind_and_advance(_cards(4, 5, 6), "selected_komissia_id", session)
    assert session["selected_komissia_id"] == 5
    assert GO_NEXT_KEY not in session
    assert ACTIVE_QUEUE_KEY in session


def test_filter_reset_clears_all_stage_details_but_not_unrelated_state(monkeypatch):
    session = {
        "selected_torgi_id": 1,
        "selected_komissia_id": 2,
        "selected_razygr_id": 3,
        ACTIVE_QUEUE_KEY: "selected_torgi_id",
        GO_NEXT_KEY: True,
        GO_NEXT_FROM_KEY: 1,
        "_catf_torgi_cats": {"paint"},
        "keep_me": 42,
    }
    import src.ui.analytics_contour_v2_page as page
    monkeypatch.setattr(page.st, "session_state", session)
    _reset_analytics_filters_state(session)
    assert session == {"keep_me": 42}


def test_commission_card_never_labels_closed_deadline_as_actionable():
    view = compose_annotation_card_view(
        header={
            "id": 8,
            "source_table": "reestr_contract_44_fz",
            "award_status": "submission_closed_waiting_award",
            "crm_stage": "torgi",
            "initial_price": 100,
            "end_date": "2026-08-10",
        },
        resolved={"links": []},
        observations=[],
        history=[],
    )
    assert view["facts"]["lifecycle"] == "COMMISSION"
    assert view["facts"]["deadline_label"] == "Приём заявок завершён"


def test_normal_stage_route_no_longer_uses_legacy_inline_detail_renderer():
    source = Path("src/ui/components/analytics_v2/tabs.py").read_text(encoding="utf-8")
    assert "render_stage_workspace" in source
    assert "render_compact_card(" not in source


def test_separate_annotation_page_is_not_a_sidebar_product_route():
    source = Path("src/ui/nav.py").read_text(encoding="utf-8")
    pages_block = source.split("PAGES = {", 1)[1].split("}", 1)[0]
    assert '"objects_v2"' in pages_block
    assert '"expert_annotation"' not in pages_block
