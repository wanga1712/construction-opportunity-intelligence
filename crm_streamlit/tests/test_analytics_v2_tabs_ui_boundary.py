from contextlib import nullcontext

import pytest

from src.ui.components.analytics_v2 import tabs


class FakeCache:
    def clear(self):
        raise AssertionError("cache clear was not expected")


class FakeStreamlit:
    def __init__(self):
        self.events = []
        self.session_state = {}
        self.cache_data = FakeCache()

    def tabs(self, labels):
        self.events.append(("tabs", labels))
        return [nullcontext() for _ in labels]

    def columns(self, widths):
        self.events.append(("columns", widths))
        # Support variable number of returned columns
        if isinstance(widths, int):
            return [nullcontext() for _ in range(widths)]
        return [nullcontext() for _ in range(len(widths))]

    def selectbox(self, label, options, **kwargs):
        self.events.append(("selectbox", label, options, kwargs))
        return options[kwargs.get("index", 0)]

    def button(self, label, **kwargs):
        self.events.append(("button", label, kwargs))
        return False

    def info(self, message):
        self.events.append(("info", message))

    def caption(self, message):
        self.events.append(("caption", message))

    def markdown(self, body, **kwargs):
        self.events.append(("markdown", body))

    def radio(self, label, options, **kwargs):
        self.events.append(("radio", label, options))
        return options[0]

    def number_input(self, label, min_value=None, max_value=None, value=None, **kwargs):
        self.events.append(("number_input", label, value))
        return value or 1

    def write(self, *args, **kwargs):
        self.events.append(("write", args))


def test_tabs_names_order_payload_and_return_without_database(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(tabs, "st", fake_st)
    monkeypatch.setattr(tabs, "render_card_feed", lambda: fake_st.events.append("leads"))
    monkeypatch.setattr(tabs, "_render_torgi_tab", lambda: fake_st.events.append("torgi"))
    monkeypatch.setattr(tabs, "_render_komissia_tab", lambda: fake_st.events.append("komissia"))
    monkeypatch.setattr(tabs, "_render_review_tab", lambda: fake_st.events.append("review"))
    monkeypatch.setattr(tabs, "_render_razygranye_tab", lambda: fake_st.events.append("razygranye"))

    result = tabs.render_tabs()

    assert result is None
    assert fake_st.events == [
        ("tabs", ["Лиды", "Подготовка к торгам", "Идут торги", "Комиссия", "На рассмотрении", "Разыгранные"]),
        "leads",
        ("info", "Раздел будет подключён на следующем этапе"),
        "torgi",
        "komissia",
        "review",
        "razygranye",
    ]


def test_tabs_empty_data_uses_existing_messages_without_database(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(tabs, "st", fake_st)
    monkeypatch.setattr(tabs, "_load_sync_info", lambda *args, **kwargs: {})
    monkeypatch.setattr(tabs, "_load_torgi", lambda *args, **kwargs: [])
    monkeypatch.setattr(tabs, "_load_razygranye", lambda *args, **kwargs: [])

    tabs._render_torgi_tab()
    tabs._render_razygranye_tab()

    info_messages = [event[1] for event in fake_st.events if event[0] == "info"]
    assert info_messages == [
        "Нет тендеров в стадии торгов.",
        "Нет разыгранных закупок.",
    ]
    assert fake_st.session_state == {}


def test_tabs_preserves_renderer_error(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(tabs, "st", fake_st)

    def fail():
        raise RuntimeError("tab payload unavailable")

    monkeypatch.setattr(tabs, "render_card_feed", fail)

    with pytest.raises(RuntimeError, match="tab payload unavailable"):
        tabs.render_tabs()
