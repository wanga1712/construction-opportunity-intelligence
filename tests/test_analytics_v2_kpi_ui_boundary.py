from contextlib import nullcontext

import pytest

from src.ui.components.analytics_v2 import kpi_row


class FakeStreamlit:
    def __init__(self):
        self.metrics = []

    def columns(self, count):
        assert count == 5
        return [nullcontext() for _ in range(count)]

    def metric(self, label, value):
        self.metrics.append((label, value))


def test_kpi_payload_names_values_order_and_no_mutation(monkeypatch):
    fake_st = FakeStreamlit()
    original = list(kpi_row.KPI_VALUES)
    monkeypatch.setattr(kpi_row, "st", fake_st)

    result = kpi_row.render_kpi_row()

    assert result is None
    assert fake_st.metrics == [
        ("Новые", 29),
        ("Gold", 3),
        ("Silver", 6),
        ("Bronze", 8),
        ("Wood", 12),
    ]
    assert kpi_row.KPI_VALUES == original


def test_kpi_empty_and_zero_values(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(kpi_row, "st", fake_st)
    monkeypatch.setattr(kpi_row, "KPI_VALUES", [])

    kpi_row.render_kpi_row()
    assert fake_st.metrics == []

    monkeypatch.setattr(kpi_row, "KPI_VALUES", [("Zero", 0)])
    kpi_row.render_kpi_row()
    assert fake_st.metrics == [("Zero", 0)]


def test_kpi_missing_value_preserves_error(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(kpi_row, "st", fake_st)
    monkeypatch.setattr(kpi_row, "KPI_VALUES", [("Missing",)])

    with pytest.raises(ValueError):
        kpi_row.render_kpi_row()

    assert fake_st.metrics == []
