"""Performance / lazy-render contracts for Analytics V3 UI."""
from __future__ import annotations

import ast
from pathlib import Path

from src.services.v3_analytics_okpd import filter_okpd_rows
from src.services.v3_analytics_precutover import PreCutoverFileCache, make_file_lock_pair
from src.services.v3_analytics_read import apply_contour_filter_to_payload, read_dashboard
from src.ui import v3_analytics_okpd_funnel as funnel
from src.ui import v3_analytics_page as page

ROOT = Path(__file__).resolve().parents[1]
UI_PAGE = ROOT / "src" / "ui" / "v3_analytics_page.py"
UI_FUNNEL = ROOT / "src" / "ui" / "v3_analytics_okpd_funnel.py"


def _many_okpd_rows(n: int = 725):
    rows = []
    for i in range(n):
        code = f"27.{i % 100:02d}.{i:03d}"
        rows.append(
            {
                "okpd_code": code,
                "okpd_name": f"name-{i}",
                "source_received": i,
                "technically_eligible": i,
                "technically_rejected": 0,
                "title_negative_signal": "NOT_STARTED",
                "hard_excluded": "NOT_STARTED",
                "projected_to_crm": i // 2,
                "pending_routing": "NOT_STARTED",
                "routed": "NOT_STARTED",
                "candidate_gold": "NOT_STARTED",
                "source_44": i,
                "source_223": 0,
                "prepared_prior_categories": [
                    {"category_code": "lighting", "display_name": "Освещение", "label": "PREPARED PRIOR"}
                ]
                if i % 3 == 0
                else [],
            }
        )
    return rows


def test_initial_okpd_render_limit():
    assert funnel.INITIAL_OKPD_RENDER_LIMIT <= 50
    assert funnel.DEFAULT_PAGE_SIZE in (25, 50)
    assert funnel.DEFAULT_PAGE_SIZE <= funnel.INITIAL_OKPD_RENDER_LIMIT
    assert funnel.FILTER_BEFORE_RENDER is True
    assert funnel.DRILLDOWN_EAGER_FOR_ALL_OKPD is False
    assert funnel.DRILLDOWN_BUILD_ON_SELECTION is True
    assert funnel.CATEGORY_TREE_LAZY is True
    assert funnel.ONE_DETAIL_TREE_AT_A_TIME is True


def test_pagination_filter_before_render_slice():
    rows = _many_okpd_rows(725)
    filtered, page_rows, total, pages = funnel.prepare_okpd_page(
        rows, contour="ALL", okpd_q="", category="ALL", page=1, page_size=25
    )
    assert total == 725
    assert len(page_rows) == 25
    assert len(page_rows) <= funnel.INITIAL_OKPD_RENDER_LIMIT
    assert pages == 29
    table = funnel.rows_to_table(page_rows)
    assert len(table) == 25
    assert "payload_json" not in table[0]


def test_filter_reduces_before_slice():
    rows = _many_okpd_rows(100)
    rows[7]["okpd_code"] = "42.11.20.900"
    _, page_rows, total, pages = funnel.prepare_okpd_page(
        rows, contour="ALL", okpd_q="42.11", category="ALL", page=1, page_size=50
    )
    assert total == 1
    assert len(page_rows) == 1
    assert pages == 1


def test_page_contracts_flags():
    assert page.HIDDEN_SECTIONS_HEAVY_RENDER is False
    assert page.PAGE_LOAD_WAITS_FOR_REFRESH is False
    assert page.FULL_SNAPSHOT_IN_SESSION_STATE is False
    assert page.SNAPSHOT_FILE_READS_PER_RERUN <= 1
    assert page.SNAPSHOT_JSON_PARSES_PER_RERUN <= 1
    assert page.DASHBOARD_READ_ACQUIRES_REFRESH_LOCK is False
    assert page.N_PLUS_ONE_ANALYTICS_QUERIES is False
    assert page.REFRESH_BLOCKS_DASHBOARD_READ is False


def test_page_uses_radio_not_tabs_for_sections():
    src = UI_PAGE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = []

    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "tabs":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "st":
                    calls.append("st.tabs")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "radio":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "st":
                    calls.append("st.radio")
            self.generic_visit(node)

    V().visit(tree)
    assert "st.tabs" not in calls
    assert "st.radio" in calls
    assert "HIDDEN_SECTIONS_HEAVY_RENDER = False" in src


def test_funnel_has_no_expanders_for_all_rows():
    src = UI_FUNNEL.read_text(encoding="utf-8")
    assert "st.expander" not in src


def test_snapshot_read_once_per_load(tmp_path):
    store = PreCutoverFileCache(root=tmp_path)
    gen = store.start_generation("test")
    from src.services.v3_analytics_cache import SnapshotRow

    store.write_rows(
        gen.generation_id,
        [
            SnapshotRow(
                snapshot_key="dash",
                metric_group="DASHBOARD",
                metric_name="snapshot",
                metric_value=1,
                payload_json={"source_open": 1, "okpd_funnel": {"rows": [], "meta": {"okpd_group_count": 0}}},
            )
        ],
    )
    store.complete_generation(
        gen.generation_id,
        duration_ms=1,
        source_query_ms=1,
        crm_query_ms=0,
        cache_write_ms=1,
        metrics_collected=1,
    )
    reads = {"n": 0}
    orig = store.load_dashboard_payload

    def counted(gid):
        reads["n"] += 1
        return orig(gid)

    store.load_dashboard_payload = counted  # type: ignore
    v1 = read_dashboard(store)
    v2 = read_dashboard(store)
    assert v1.ready and v2.ready
    assert reads["n"] == 2  # each read_dashboard once — contract for page is cache wrapper
    assert v1.s7_queries == 0


def test_dashboard_read_does_not_use_refresh_lock(tmp_path):
    store = PreCutoverFileCache(root=tmp_path)
    lock_try, lock_release = make_file_lock_pair(tmp_path)
    assert lock_try() is True
    try:
        # Holding refresh lock must not block dashboard read (readers ignore lock)
        gen = store.start_generation("t")
        from src.services.v3_analytics_cache import SnapshotRow

        store.write_rows(
            gen.generation_id,
            [
                SnapshotRow(
                    snapshot_key="dash",
                    metric_group="DASHBOARD",
                    metric_name="snapshot",
                    metric_value=1,
                    payload_json={"source_open": 3},
                )
            ],
        )
        store.complete_generation(
            gen.generation_id,
            duration_ms=1,
            source_query_ms=0,
            crm_query_ms=0,
            cache_write_ms=0,
            metrics_collected=1,
        )
        view = read_dashboard(store)
        assert view.ready
        assert view.data.get("source_open") == 3
    finally:
        lock_release()


def test_contour_filter_is_shallow_not_deepcopy():
    rows = _many_okpd_rows(10)
    data = {"source_open": 10, "okpd_funnel": {"rows": rows}, "source_44_open": 7, "source_223_open": 3}
    out = apply_contour_filter_to_payload(data, "44")
    assert out["okpd_funnel"] is data["okpd_funnel"]
    assert out["source_open"] == 7


def test_filter_okpd_rows_matches_prepare():
    rows = _many_okpd_rows(50)
    a = filter_okpd_rows(rows, okpd_query="27.01")
    _, page, total, _ = funnel.prepare_okpd_page(
        rows, contour="ALL", okpd_q="27.01", category="ALL", page=1, page_size=25
    )
    assert total == len(a)
    assert len(page) <= 25
