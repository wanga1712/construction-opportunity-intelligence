from contextlib import nullcontext

from src.ui.components.analytics_v2 import quick_filters


class FakeStreamlit:
    def __init__(self, sort_value="По приоритету", view_value="Карточки"):
        self.sort_value = sort_value
        self.view_value = view_value
        self.calls = []
        self.session_state = {}

    def columns(self, widths):
        self.calls.append(("columns", widths))
        return nullcontext(), nullcontext()

    def selectbox(self, label, options, **kwargs):
        self.calls.append(("selectbox", label, options, kwargs))
        self.session_state[kwargs["key"]] = self.sort_value
        return self.sort_value

    def segmented_control(self, label, options, **kwargs):
        self.calls.append(("segmented_control", label, options, kwargs))
        self.session_state[kwargs["key"]] = self.view_value
        return self.view_value


def test_quick_filters_options_order_defaults_keys_and_return(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(quick_filters, "st", fake_st)

    result = quick_filters.render_quick_filters()

    assert result is None
    assert fake_st.calls == [
        ("columns", [3, 1]),
        (
            "selectbox",
            "Сортировка",
            ["По приоритету", "По дате обновления", "По стадии"],
            {"index": 0, "key": "analytics_v2_sort", "label_visibility": "collapsed"},
        ),
        (
            "segmented_control",
            "Вид",
            ["Карточки", "Таблица"],
            {
                "default": "Карточки",
                "selection_mode": "single",
                "key": "analytics_v2_view_mode",
                "label_visibility": "collapsed",
            },
        ),
    ]
    assert fake_st.session_state == {
        "analytics_v2_sort": "По приоритету",
        "analytics_v2_view_mode": "Карточки",
    }


def test_quick_filters_changed_and_unknown_values_are_not_transformed(monkeypatch):
    fake_st = FakeStreamlit(sort_value="По стадии", view_value="Неизвестно")
    monkeypatch.setattr(quick_filters, "st", fake_st)

    result = quick_filters.render_quick_filters()

    assert result is None
    assert fake_st.session_state == {
        "analytics_v2_sort": "По стадии",
        "analytics_v2_view_mode": "Неизвестно",
    }
    select_options = fake_st.calls[1][2]
    view_options = fake_st.calls[2][2]
    assert select_options
    assert view_options
