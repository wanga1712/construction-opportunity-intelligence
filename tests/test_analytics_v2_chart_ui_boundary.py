from contextlib import nullcontext

import pytest

from src.ui import analytics_contour_v2_page as page


class FakeStreamlit:
    def __init__(self, events):
        self.events = events
        self.session_state = {}

    def markdown(self, *args, **kwargs):
        self.events.append("markdown")

    def divider(self):
        self.events.append("divider")

    def columns(self, *args, **kwargs):
        self.events.append("columns")
        return nullcontext(), nullcontext()


def _patch_page(monkeypatch, cards):
    events = []
    fake_st = FakeStreamlit(events)
    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setattr(page, "CARDS", cards)
    monkeypatch.setattr(page, "render_header", lambda: events.append("header"))
    monkeypatch.setattr(page, "render_kpi_row", lambda: events.append("kpi"))
    monkeypatch.setattr(page, "render_limits", lambda: events.append("limits"))
    monkeypatch.setattr(page, "render_charts", lambda: events.append("charts"))
    monkeypatch.setattr(page, "_render_filters", lambda _repository: events.append("filters"))
    monkeypatch.setattr(page, "render_quick_filters", lambda: events.append("quick"))
    monkeypatch.setattr(page, "render_tabs", lambda: events.append("tabs"))
    return fake_st, events


def test_ui_boundary_preserves_chart_order_payload_identity_and_return(monkeypatch):
    cards = [{"id": 2}, {"id": 1}]
    fake_st, events = _patch_page(monkeypatch, cards)

    result = page.render_analytics_contour_v2_page(object())

    assert result is None
    assert fake_st.session_state["analytics_v2_cards"] is cards
    assert events == [
        "markdown",
        "header",
        "kpi",
        "limits",
        "divider",
        "charts",
        "divider",
        "columns",
        "filters",
        "quick",
        "tabs",
    ]


def test_ui_boundary_renders_charts_for_empty_cards(monkeypatch):
    fake_st, events = _patch_page(monkeypatch, [])

    page.render_analytics_contour_v2_page(object())

    assert fake_st.session_state["analytics_v2_cards"] == []
    assert events.count("charts") == 1


def test_ui_boundary_preserves_chart_error(monkeypatch):
    _, events = _patch_page(monkeypatch, [])

    def fail():
        events.append("charts")
        raise RuntimeError("chart data unavailable")

    monkeypatch.setattr(page, "render_charts", fail)

    with pytest.raises(RuntimeError, match="chart data unavailable"):
        page.render_analytics_contour_v2_page(object())

    assert events[-1] == "charts"


def test_ui_boundary_owns_header_call_and_preserves_error(monkeypatch):
    _, events = _patch_page(monkeypatch, [])

    def fail():
        events.append("header")
        raise RuntimeError("header unavailable")

    monkeypatch.setattr(page, "render_header", fail)

    with pytest.raises(RuntimeError, match="header unavailable"):
        page.render_analytics_contour_v2_page(object())

    assert events == ["markdown", "header"]
