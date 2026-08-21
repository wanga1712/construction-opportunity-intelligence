from __future__ import annotations

import ast
from pathlib import Path

import app as root_app
from src.ui import app_bootstrap


PAGE_CONFIG = {
    "page_title": "CRM Система",
    "page_icon": "🏢",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}


def test_production_entrypoint_runs_each_boundary_once_in_order(monkeypatch):
    events = []
    configs = []

    monkeypatch.setattr(
        root_app.st,
        "set_page_config",
        lambda **kwargs: (configs.append(kwargs), events.append("set_page_config")),
    )
    monkeypatch.setattr(
        root_app,
        "inject_global_styles",
        lambda: events.append("inject_global_styles"),
    )
    monkeypatch.setattr(
        root_app,
        "run_app_bootstrap",
        lambda: events.append("app_bootstrap.main"),
    )

    root_app.main()

    assert configs == [PAGE_CONFIG]
    assert events == [
        "set_page_config",
        "inject_global_styles",
        "app_bootstrap.main",
    ]


def test_bootstrap_runs_watchdog_navigation_and_renderer_once(monkeypatch):
    events = []
    monkeypatch.setattr(
        app_bootstrap,
        "_db_connection_watchdog",
        lambda: events.append("watchdog"),
    )
    monkeypatch.setattr(
        app_bootstrap,
        "render_sidebar_nav",
        lambda: events.append("navigation") or "objects_v2",
    )
    monkeypatch.setattr(
        app_bootstrap,
        "_get_service",
        lambda **kwargs: events.append("dependency/session_state") or object(),
    )
    monkeypatch.setattr(app_bootstrap, "render_db_status_banner", lambda: None)
    monkeypatch.setattr(
        app_bootstrap,
        "render_analytics_contour_v2_page",
        lambda service: events.append("renderer"),
    )

    app_bootstrap.main()

    assert events == [
        "navigation",
        "watchdog",
        "dependency/session_state",
        "renderer",
    ]


def test_bootstrap_system_health_skips_companies_dependency(monkeypatch):
    events = []
    monkeypatch.setattr(
        app_bootstrap,
        "render_sidebar_nav",
        lambda: events.append("navigation") or "system_health",
    )
    monkeypatch.setattr(
        app_bootstrap,
        "_get_service",
        lambda **kwargs: events.append("dependency/session_state") or object(),
    )
    monkeypatch.setattr(
        app_bootstrap,
        "render_system_health_page",
        lambda service=None: events.append("renderer"),
    )

    app_bootstrap.main()

    assert events == ["navigation", "renderer"]


def test_page_config_exists_only_in_root_launcher():
    root_source = Path(root_app.__file__).read_text(encoding="utf-8")
    bootstrap_source = Path(app_bootstrap.__file__).read_text(encoding="utf-8")

    assert root_source.count("set_page_config(") == 1
    assert "set_page_config(" not in bootstrap_source
    assert root_source.count("inject_global_styles()") == 1
    assert root_source.count("run_app_bootstrap()") == 1


def test_root_launcher_has_no_routing_or_session_state():
    root_source = Path(root_app.__file__).read_text(encoding="utf-8")
    tree = ast.parse(root_source)
    imported_modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "src.ui.app_bootstrap" in imported_modules
    assert "src.ui.styles" in imported_modules
    assert "session_state" not in root_source
    assert "page ==" not in root_source
    assert "_get_service" not in root_source
