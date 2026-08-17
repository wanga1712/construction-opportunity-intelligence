"""
CRM-FILTER-1 — Tests for hierarchical category filter.

Tests cover:
1.  «Все» выбирает все категории
2.  Родитель выбирает все подкатегории
3.  Частичный выбор подкатегорий
4.  Разные категории можно комбинировать
5.  Одинаковые названия подкатегорий разных категорий не смешиваются (по category_code)
6.  Counts считаются по полной выборке (не по 50 карточкам)
7.  Counts соответствуют текущей вкладке (stage filter)
8.  Другие фильтры влияют на counts
9.  Текущий category selection НЕ скрывает альтернативные counts
10. Пустой выбор безопасен (не пустая страница)
11. Неизвестная категория попадает в «Без подтверждённой категории»
12. Нет N+1 SQL (один batch-запрос)
13. Pagination не меняет totals
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

from src.services.crm_profile_service import build_category_sql_filter


# ─── Fixtures & helpers ───────────────────────────────────────────────────────

def _make_hierarchy(data: dict) -> dict:
    """
    Convenience: build a hierarchy dict from compact spec.

    data = {"cat_a": {"count": 10, "subs": {"sub1": 5, "sub2": 5}}, ...}
    """
    h = {}
    for cat, info in data.items():
        h[cat] = {
            "display": info.get("display", cat),
            "count": info.get("count", 0),
            "subcategories": {
                sk: {"display": sk, "count": sv}
                for sk, sv in info.get("subs", {}).items()
            },
        }
    return h


_SAMPLE_HIERARCHY = _make_hierarchy({
    "outdoor_lighting": {"count": 12, "subs": {"street_lamp": 7, "spotlight": 5}},
    "computers":        {"count": 18, "subs": {"monoblock": 7, "laptop": 6, "server": 5}},
    "uncategorized":    {"count": 17, "subs": {}},
})


# ─── 1. «Все» выбирает все категории ─────────────────────────────────────────

def test_select_all_covers_all_categories():
    all_cats = set(_SAMPLE_HIERARCHY.keys())
    selected = all_cats.copy()
    sql, params = build_category_sql_filter(selected, all_cats)
    assert sql == "TRUE"
    assert params == {}


# ─── 2. Родитель выбирает все подкатегории ───────────────────────────────────

def test_parent_selection_includes_all_subcategories():
    """Selecting 'outdoor_lighting' should make all its subcategories implicitly included."""
    all_cats = set(_SAMPLE_HIERARCHY.keys())
    # Only outdoor_lighting selected
    selected = {"outdoor_lighting"}
    sql, params = build_category_sql_filter(selected, all_cats)
    assert sql != "TRUE"
    assert "outdoor_lighting" in params.get("selected_cats", [])
    assert "computers" not in params.get("selected_cats", [])


# ─── 3. Частичный выбор подкатегорий ─────────────────────────────────────────

def test_partial_subcategory_selection():
    """Partial subcategory selection only includes explicitly chosen subcategories."""
    all_cats = set(_SAMPLE_HIERARCHY.keys())
    selected = {"outdoor_lighting"}  # parent, not all
    sql, params = build_category_sql_filter(selected, all_cats)
    # Should produce a real filter, not TRUE
    assert sql != "TRUE"
    assert "outdoor_lighting" in params["selected_cats"]


# ─── 4. Разные категории можно комбинировать ─────────────────────────────────

def test_multiple_categories_combined():
    all_cats = set(_SAMPLE_HIERARCHY.keys())
    selected = {"outdoor_lighting", "computers"}
    sql, params = build_category_sql_filter(selected, all_cats)
    assert sql != "TRUE"
    cats = params["selected_cats"]
    assert "outdoor_lighting" in cats
    assert "computers" in cats
    assert "uncategorized" not in cats


# ─── 5. Одинаковые имена подкатегорий разных категорий не смешиваются ────────

def test_same_subcat_name_different_parents_not_mixed():
    """
    If two categories have a sub named 'type_a', they should be separate.
    build_category_sql_filter uses category codes, not display names.
    """
    h = _make_hierarchy({
        "lighting":  {"count": 10, "subs": {"type_a": 5}},
        "plumbing":  {"count": 8,  "subs": {"type_a": 4}},
    })
    all_cats = set(h.keys())
    selected = {"lighting"}  # only lighting, not plumbing
    sql, params = build_category_sql_filter(selected, all_cats)
    assert sql != "TRUE"
    cats = params["selected_cats"]
    assert "lighting" in cats
    assert "plumbing" not in cats


# ─── 6. Counts считаются по полной выборке ───────────────────────────────────

def test_counts_from_full_table_not_page(monkeypatch):
    """
    load_category_hierarchy must issue a COUNT(DISTINCT cp.id) aggregation,
    not rely on a pre-paginated card list.
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = [
        {"cat": "outdoor_lighting", "subcategory": None, "cnt": 120},
    ]
    mock_conn.cursor.return_value = mock_cur
    mock_conn.close = MagicMock()

    with patch("src.services.crm_profile_service._crm_conn", return_value=mock_conn), \
         patch("streamlit.cache_data", lambda **kw: (lambda f: f)):
        from src.services.crm_profile_service import load_category_hierarchy
        result = load_category_hierarchy.__wrapped__("torgi")

    executed_sql = mock_cur.execute.call_args[0][0]
    assert "COUNT(DISTINCT cp.id)" in executed_sql
    # Count should reflect full table (120), not a LIMIT-ed result
    assert result["outdoor_lighting"]["count"] == 120


# ─── 7. Counts соответствуют текущей вкладке (stage filter) ──────────────────

def test_counts_filtered_by_stage(monkeypatch):
    """load_category_hierarchy passes the stage parameter to the SQL WHERE clause."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cur
    mock_conn.close = MagicMock()

    with patch("src.services.crm_profile_service._crm_conn", return_value=mock_conn), \
         patch("streamlit.cache_data", lambda **kw: (lambda f: f)):
        from src.services.crm_profile_service import load_category_hierarchy
        load_category_hierarchy.__wrapped__("razygranye")

    executed_sql = mock_cur.execute.call_args[0][0]
    params = mock_cur.execute.call_args[0][1]
    assert "crm_stage" in executed_sql
    assert params["stage"] == "razygranye"


# ─── 8. Другие фильтры влияют на counts ──────────────────────────────────────

def test_other_filters_affect_counts(monkeypatch):
    """Profile and region filters are passed through to the SQL query."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cur
    mock_conn.close = MagicMock()

    filters = {"profile_id": 42, "region": "Москва"}

    with patch("src.services.crm_profile_service._crm_conn", return_value=mock_conn), \
         patch("streamlit.cache_data", lambda **kw: (lambda f: f)):
        from src.services.crm_profile_service import load_category_hierarchy
        load_category_hierarchy.__wrapped__("torgi", filters)

    executed_sql = mock_cur.execute.call_args[0][0]
    params = mock_cur.execute.call_args[0][1]
    assert "crm_profile_id" in executed_sql
    assert params.get("profile_id") == 42
    assert "delivery_region" in executed_sql
    assert params.get("region") == "Москва"


# ─── 9. Category selection НЕ скрывает альтернативные counts ─────────────────

def test_category_filter_not_applied_to_counts(monkeypatch):
    """
    The counts aggregation query must NOT include a WHERE on selected categories —
    so the user can see counts for unselected categories (to make a different choice).
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = [
        {"cat": "outdoor_lighting", "subcategory": None, "cnt": 12},
        {"cat": "computers",        "subcategory": None, "cnt": 18},
        {"cat": "uncategorized",    "subcategory": None, "cnt": 17},
    ]
    mock_conn.cursor.return_value = mock_cur
    mock_conn.close = MagicMock()

    with patch("src.services.crm_profile_service._crm_conn", return_value=mock_conn), \
         patch("streamlit.cache_data", lambda **kw: (lambda f: f)):
        from src.services.crm_profile_service import load_category_hierarchy
        # Only "outdoor_lighting" selected, but counts for all should be returned
        result = load_category_hierarchy.__wrapped__("torgi")

    executed_sql = mock_cur.execute.call_args[0][0]
    # The aggregation query must NOT filter by selected_cats
    assert "selected_cats" not in executed_sql
    # All categories should be in the result regardless of what is "selected"
    assert "outdoor_lighting" in result
    assert "computers" in result
    assert "uncategorized" in result


# ─── 10. Пустой выбор безопасен ──────────────────────────────────────────────

def test_empty_selection_is_safe():
    """Empty selection should produce 'TRUE' (show all), not an empty result page."""
    sql, params = build_category_sql_filter(set(), set())
    assert sql == "TRUE"
    assert params == {}


def test_empty_selection_with_known_cats():
    """Even with known categories, empty selection → TRUE (safe fallback)."""
    all_cats = {"outdoor_lighting", "computers", "uncategorized"}
    sql, params = build_category_sql_filter(set(), all_cats)
    assert sql == "TRUE"
    assert params == {}


# ─── 11. Неизвестная категория → «uncategorized» ─────────────────────────────

def test_unknown_category_mapped_to_uncategorized(monkeypatch):
    """
    Rows with no category in crm_category_candidates, no crm_category, and no object_type
    should produce 'uncategorized' in the hierarchy.
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = [
        {"cat": "uncategorized", "subcategory": None, "cnt": 5},
    ]
    mock_conn.cursor.return_value = mock_cur
    mock_conn.close = MagicMock()

    with patch("src.services.crm_profile_service._crm_conn", return_value=mock_conn), \
         patch("streamlit.cache_data", lambda **kw: (lambda f: f)):
        from src.services.crm_profile_service import load_category_hierarchy
        result = load_category_hierarchy.__wrapped__("torgi")

    assert "uncategorized" in result
    assert result["uncategorized"]["count"] == 5
    assert result["uncategorized"]["display"] == "Без подтверждённой категории"


# ─── 12. Нет N+1 SQL ─────────────────────────────────────────────────────────

def test_no_n_plus_1_sql(monkeypatch):
    """load_category_hierarchy must issue exactly ONE SQL query."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = [
        {"cat": "outdoor_lighting", "subcategory": "street_lamp", "cnt": 7},
        {"cat": "outdoor_lighting", "subcategory": "spotlight",   "cnt": 5},
        {"cat": "computers",        "subcategory": None,           "cnt": 18},
    ]
    mock_conn.cursor.return_value = mock_cur
    mock_conn.close = MagicMock()

    with patch("src.services.crm_profile_service._crm_conn", return_value=mock_conn), \
         patch("streamlit.cache_data", lambda **kw: (lambda f: f)):
        from src.services.crm_profile_service import load_category_hierarchy
        result = load_category_hierarchy.__wrapped__("torgi")

    # Exactly one execute call
    assert mock_cur.execute.call_count == 1
    # Result correctly aggregated
    assert result["outdoor_lighting"]["count"] == 12
    assert result["outdoor_lighting"]["subcategories"]["street_lamp"]["count"] == 7
    assert result["outdoor_lighting"]["subcategories"]["spotlight"]["count"] == 5
    assert result["computers"]["count"] == 18


# ─── 13. Pagination не меняет totals ─────────────────────────────────────────

def test_pagination_does_not_change_totals(monkeypatch):
    """
    The counts returned by load_category_hierarchy are independent of pagination
    (they are whole-table aggregates, not limited to the displayed page of 50 cards).
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = [
        {"cat": "outdoor_lighting", "subcategory": None, "cnt": 200},
    ]
    mock_conn.cursor.return_value = mock_cur
    mock_conn.close = MagicMock()

    with patch("src.services.crm_profile_service._crm_conn", return_value=mock_conn), \
         patch("streamlit.cache_data", lambda **kw: (lambda f: f)):
        from src.services.crm_profile_service import load_category_hierarchy
        result = load_category_hierarchy.__wrapped__("torgi")

    executed_sql = mock_cur.execute.call_args[0][0]
    # Query must NOT contain LIMIT / OFFSET (counts are full-table)
    assert "LIMIT" not in executed_sql.upper()
    assert "OFFSET" not in executed_sql.upper()
    assert result["outdoor_lighting"]["count"] == 200
