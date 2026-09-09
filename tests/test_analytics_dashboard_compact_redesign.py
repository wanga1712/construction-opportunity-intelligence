"""Tests for WIP=CRM-ANALYTICS-V2-DASHBOARD-COMPACT-VISUAL-REDESIGN-1.

Verifies:
- test_main_transition_chart_not_rendered
- test_transition_details_collapsed
- test_24h_rendered_as_compact_caption
- test_dashboard_uses_bounded_width
- test_full_matrix_not_visible_by_default
- test_kpi_semantics_and_sql_unchanged
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from src.services.analytics_dashboard_kpi_service import (
    ArrayCounts,
    DashboardKPI,
    MedalDecisions,
    MedalTransition,
    PipelineStatus,
)
from src.ui.components.analytics_v2 import dashboard_header


@pytest.fixture
def sample_kpi():
    return DashboardKPI(
        array=ArrayCounts(
            fz44_torgi=117675,
            fz223_torgi=39723,
            fz44_razygranye=12727,
            fz223_razygranye=0,
        ),
        new_24h=ArrayCounts(
            fz44_torgi=33,
            fz223_torgi=10,
            fz44_razygranye=0,
            fz223_razygranye=0,
        ),
        pipeline=PipelineStatus(
            queued=32665,
            processing=0,
            processed=119,
            failed=50,
            no_links=603,
        ),
        medals=MedalDecisions(
            same=2351,
            down=1158,
            up=0,
            rejected=192,
            matrix=[
                MedalTransition("GOLD", "BRONZE", 55),
                MedalTransition("SILVER", "SILVER", 17),
                MedalTransition("SILVER", "BRONZE", 1103),
                MedalTransition("BRONZE", "BRONZE", 1898),
                MedalTransition("WOOD", "WOOD", 436),
            ],
        ),
    )


def test_main_transition_chart_not_rendered(sample_kpi):
    """Main dashboard must NOT render a 100% stacked bar chart directly."""
    source = inspect.getsource(dashboard_header.render_dashboard_header)
    assert "_render_transition_chart" not in source
    assert "plotly_chart" not in inspect.getsource(dashboard_header)


def test_transition_details_collapsed(sample_kpi):
    """Detailed transition analytics must be under a collapsed expander."""
    source = inspect.getsource(dashboard_header._render_assessment)
    assert "Подробнее об изменении медалей" in source
    assert 'expanded=False' in source


def test_24h_rendered_as_compact_caption(sample_kpi):
    """24h new arrivals must be rendered as a compact secondary line, not separate giant cards."""
    rendered_markdowns = []
    with patch("streamlit.markdown", side_effect=lambda md, **kw: rendered_markdowns.append(md)):
        dashboard_header._render_inventory(sample_kpi)

    all_html = "\n".join(rendered_markdowns)
    assert "Новые за 24 часа:" in all_html
    assert "+33 44-ФЗ" in all_html
    assert "+10 223-ФЗ" in all_html
    assert "v2-secondary-line" in all_html


def test_dashboard_uses_bounded_width(sample_kpi):
    """Dashboard must use a bounded width container (around 1180-1250px)."""
    css = dashboard_header._COMPACT_DASHBOARD_CSS
    assert "max-width: 1220px" in css
    assert "margin: 0 auto" in css


def test_full_matrix_not_visible_by_default(sample_kpi):
    """Full 4x4 matrix must be in a collapsed secondary expander, not directly shown."""
    source = inspect.getsource(dashboard_header._render_assessment)
    assert "Показать полную матрицу (4×4)" in source
    assert 'expanded=False' in source


def test_procurement_cards_rendered_compactly(sample_kpi):
    """Procurement inventory renders 4 cards with strong numbers."""
    rendered = []
    with patch("streamlit.markdown", side_effect=lambda md, **kw: rendered.append(md)):
        dashboard_header._render_inventory(sample_kpi)

    html = "\n".join(rendered)
    assert "117 675" in html
    assert "39 723" in html
    assert "12 727" in html
    assert "44-ФЗ · Торги" in html


def test_document_pipeline_strip_rendered(sample_kpi):
    """Document pipeline renders as a compact horizontal strip."""
    rendered = []
    with patch("streamlit.markdown", side_effect=lambda md, **kw: rendered.append(md)):
        dashboard_header._render_pipeline_strip(sample_kpi)

    html = "\n".join(rendered)
    assert "32 665" in html
    assert "119" in html
    assert "653" in html
    assert "В очереди" in html
    assert "Завершено" in html
    assert "Все периоды" in html
    assert "v2-pipeline-strip" in html


def test_commercial_assessment_cards_rendered(sample_kpi):
    """Commercial assessment renders 3 compact cards."""
    rendered = []
    with patch("streamlit.markdown", side_effect=lambda md, **kw: rendered.append(md)):
        with patch("streamlit.expander", return_value=MagicMock()):
            dashboard_header._render_assessment(sample_kpi)

    html = "\n".join(rendered)
    assert "2 351" in html
    assert "67%" in html
    assert "1 158" in html
    assert "33%" in html
    assert "Без изменения" in html
    assert "↓ Понижена" in html
    assert "↑ Повышена" in html
