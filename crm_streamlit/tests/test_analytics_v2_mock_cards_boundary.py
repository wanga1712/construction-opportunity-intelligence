from contextlib import nullcontext

import pytest

from src.services import analytics_contour_v2_page as page
class FakeStreamlit:
    def __init__(self):
        self.session_state = {}

    def markdown(self, *args, **kwargs):
        return None

    def divider(self):
        return None

    def columns(self, *args, **kwargs):
        return nullcontext(), nullcontext()


def _isolate_render(monkeypatch, fake_st):
    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setattr(page, "_render_filters", lambda _repository: None)


def test_render_uses_injected_cards_by_identity_without_filtering_or_mutation(monkeypatch):
    fake_st = FakeStreamlit()
    _isolate_render(monkeypatch, fake_st)
    service = object()
    demo_cards = [{"id": 3}, {"id": 1}, {"id": 2}]
    before = list(demo_cards)

    page.render_analytics_contour_v2_page(service, demo_cards)

    result = fake_st.session_state["analytics_v2_cards"]
    assert result is demo_cards
    assert result == before
    assert demo_cards == before


def test_render_preserves_empty_cards_and_does_not_touch_real_source(monkeypatch):
    fake_st = FakeStreamlit()
    _isolate_render(monkeypatch, fake_st)
    class FailingRealSource:
        def __getattr__(self, name):
            raise AssertionError(f"real source unexpectedly used: {name}")

    page.render_analytics_contour_v2_page(FailingRealSource(), [])

    assert fake_st.session_state["analytics_v2_cards"] == []


def test_render_propagates_existing_renderer_error(monkeypatch):
    fake_st = FakeStreamlit()
    _isolate_render(monkeypatch, fake_st)

    def fail(_repository):
        raise RuntimeError("renderer failed")

    monkeypatch.setattr(page, "_render_filters", fail)

    with pytest.raises(RuntimeError, match="renderer failed"):
        page.render_analytics_contour_v2_page(object(), [{"id": 1}])
