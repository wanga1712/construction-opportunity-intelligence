from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from src.ui import app_bootstrap


FUNCTION_SIGNATURES = {
    "_render_startup_error": "(warn: str) -> None",
    "_create_service": "() -> Optional[src.services.companies_service.CompaniesService]",
    "_get_service": "() -> Optional[src.services.companies_service.CompaniesService]",
    "_db_connection_watchdog": "() -> None",
    "main": "() -> None",
}

ROUTES = [
    ("ai_review", "render_ai_review_page"),
    ("companies", "render_companies_page"),
    ("objects", "render_analytics_contour_page"),
    ("objects_copy", "render_analytics_contour_copy_page"),
    ("objects_v2", "render_analytics_contour_v2_page"),
    ("opportunity_radar", "render_opportunity_radar_page"),
    ("computers", "render_computers_page"),
    ("waterproofing", "render_waterproofing_page"),
    ("map", "render_map_page"),
    ("infrastructure", "render_infrastructure_page"),
    ("customers", "render_customers_page"),
    ("export_pdf", "render_export_queue_page"),
    ("crm_profiles", "render_crm_profiles_page"),
]

SESSION_KEYS = {
    "service",
    "objects_service",
    "db_warn",
    "db_online",
    "db_crm_ok",
    "db_just_reconnected",
}


def _defined_functions(module):
    return {
        name: value
        for name, value in vars(module).items()
        if inspect.isfunction(value) and value.__module__ == module.__name__
    }


def _source():
    return Path(app_bootstrap.__file__).read_text(encoding="utf-8-sig")


def test_canonical_function_exports_and_signatures():
    functions = _defined_functions(app_bootstrap)
    assert set(functions) == set(FUNCTION_SIGNATURES)
    assert {
        name: str(inspect.signature(function)) for name, function in functions.items()
    } == FUNCTION_SIGNATURES
    assert app_bootstrap.DB_WATCH_INTERVAL_SEC == 20


def test_relocated_routes_and_session_contract_are_characterized():
    source = _source()
    route_positions = []
    for route, renderer in ROUTES:
        route_position = source.index(f'page == "{route}"')
        renderer_position = source.index(f"{renderer}(", route_position)
        route_positions.append((route_position, renderer_position))
    assert route_positions == sorted(route_positions)

    for key in SESSION_KEYS:
        assert f'"{key}"' in source or f".{key}" in source


def _run_main(monkeypatch, *, page="customers", renderer_error=None):
    events = []
    monkeypatch.setattr(
        app_bootstrap,
        "_db_connection_watchdog",
        lambda: events.append("watchdog"),
    )
    monkeypatch.setattr(
        app_bootstrap,
        "render_sidebar_nav",
        lambda: events.append("navigation") or page,
    )
    monkeypatch.setattr(
        app_bootstrap,
        "_get_service",
        lambda: events.append("get_service") or object(),
    )
    monkeypatch.setattr(
        app_bootstrap,
        "render_db_status_banner",
        lambda: events.append("db_banner"),
    )
    monkeypatch.setattr(
        app_bootstrap.st,
        "info",
        lambda _message: events.append("unknown_route"),
    )

    def render_customers():
        events.append("page_render")
        if renderer_error:
            raise renderer_error

    monkeypatch.setattr(app_bootstrap, "render_customers_page", render_customers)
    app_bootstrap.main()
    return events


def test_relocated_page_selection_and_orchestration_order(monkeypatch):
    assert _run_main(monkeypatch) == [
        "watchdog",
        "navigation",
        "get_service",
        "db_banner",
        "page_render",
    ]


def test_relocated_unknown_route_behavior(monkeypatch):
    assert _run_main(monkeypatch, page="unknown") == [
        "watchdog",
        "navigation",
        "get_service",
        "db_banner",
        "unknown_route",
    ]


def test_relocated_renderer_error_propagates(monkeypatch):
    with pytest.raises(RuntimeError, match="render failed"):
        _run_main(monkeypatch, renderer_error=RuntimeError("render failed"))


def test_relocated_module_has_no_sql_or_repository_access():
    source = _source()
    tree = ast.parse(source)
    imports = [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]

    assert not any(module.startswith("src.repositories") for module in imports)
    assert not any(
        token in source.upper()
        for token in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ")
    )
