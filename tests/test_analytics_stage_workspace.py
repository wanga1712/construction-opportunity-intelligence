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


def test_initial_route_is_inline_and_has_no_open_or_back_controls():
    source = Path("src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
    assert 'return "INLINE"' in source
    assert "Открыть карточку" not in source
    assert "Назад к списку" not in source


def test_inline_sections_are_lazy_and_shared():
    source = Path("src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
    assert "SECTIONS =" in source
    assert "_render_expensive_section(pid, canonical_section)" in source
    assert "load_current_annotation_states" in source


def test_annotation_filter_has_category_gate_human_states():
    labels = [label for _, label in stage_workspace.FILTERS]
    assert labels[0] == "Все"
    assert labels[1] == "Не проверено"
    assert labels[2] == "Проверено"
    assert labels[3] == "Вне товарных категорий"
    assert "Неинтересн" in labels[4]
    assert len(labels) == 5


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


def test_real_analytics_page_uses_lazy_single_stage_dispatcher():
    source = Path("src/ui/analytics_contour_v2_page.py").read_text(encoding="utf-8")
    assert "analytics_v2.tabs_lazy_dispatch import render_tabs" in source
    assert "analytics_v2.tabs import render_tabs" not in source
