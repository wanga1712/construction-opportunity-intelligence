import pytest

from src.ui.components.analytics_v2 import limits


class FakeStreamlit:
    def __init__(self):
        self.captions = []

    def caption(self, value):
        self.captions.append(value)


def test_limits_payload_values_caption_and_no_mutation(monkeypatch):
    fake_st = FakeStreamlit()
    original = dict(limits.LIMITS)
    monkeypatch.setattr(limits, "st", fake_st)

    result = limits.render_limits()

    assert result is None
    assert fake_st.captions == [
        "Открыто: **17** из 25 · 68% · Обновления ранее открытых: бесплатно"
    ]
    assert limits.LIMITS == original


def test_limits_zero_value(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(limits, "st", fake_st)
    monkeypatch.setattr(limits, "LIMITS", {"opened": 0, "limit": 25})

    limits.render_limits()

    assert fake_st.captions == [
        "Открыто: **0** из 25 · 0% · Обновления ранее открытых: бесплатно"
    ]


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({}, KeyError),
        ({"opened": 1}, KeyError),
        ({"opened": 1, "limit": 0}, ZeroDivisionError),
        ({"opened": "bad", "limit": 25}, TypeError),
    ],
)
def test_limits_empty_missing_and_invalid_payload(monkeypatch, payload, error):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(limits, "st", fake_st)
    monkeypatch.setattr(limits, "LIMITS", payload)

    with pytest.raises(error):
        limits.render_limits()

    assert fake_st.captions == []
