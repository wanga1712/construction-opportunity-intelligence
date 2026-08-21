"""CRM UI interactive performance — page dependency and lightweight routing."""
from __future__ import annotations

from types import SimpleNamespace

import src.ui.app_bootstrap as boot
from src.ui.page_deps import (
    PageDependency,
    page_dependency,
    requires_companies_load_sync,
    requires_companies_service,
)


def test_system_health_is_no_service() -> None:
    assert page_dependency("system_health") == PageDependency.NO_SERVICE
    assert requires_companies_service("system_health") is False
    assert requires_companies_load_sync("system_health") is False


def test_companies_pages_require_service() -> None:
    for page in ("objects_v2", "analytics_v3", "map", "companies", "export_pdf"):
        assert requires_companies_service(page) is True
        assert requires_companies_load_sync(page) is True


def test_category_registry_is_crm_db_only() -> None:
    assert page_dependency("category_registry") == PageDependency.CRM_DB_ONLY
    assert requires_companies_load_sync("category_registry") is False


def test_system_health_route_skips_companies_service(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(boot, "render_sidebar_nav", lambda: "system_health")
    monkeypatch.setattr(
        boot,
        "_get_service",
        lambda **kwargs: events.append(("get_service", kwargs)) or object(),
    )
    monkeypatch.setattr(
        boot,
        "_create_service",
        lambda **kwargs: events.append(("create_service", kwargs)) or object(),
    )
    monkeypatch.setattr(
        boot,
        "_db_connection_watchdog",
        lambda: events.append("watchdog"),
    )
    monkeypatch.setattr(boot, "render_db_status_banner", lambda: events.append("banner"))
    monkeypatch.setattr(
        boot,
        "render_system_health_page",
        lambda service=None: events.append(("system_health", service)),
    )

    boot.main()

    assert ("system_health", None) in events
    assert not any(e == "watchdog" or (isinstance(e, tuple) and e[0] in ("get_service", "create_service")) for e in events)


def test_objects_v2_still_gets_companies_service(monkeypatch) -> None:
    events: list[str] = []
    svc = object()

    monkeypatch.setattr(boot, "render_sidebar_nav", lambda: "objects_v2")
    monkeypatch.setattr(boot, "_db_connection_watchdog", lambda: events.append("watchdog"))
    monkeypatch.setattr(
        boot,
        "_get_service",
        lambda **kwargs: events.append(("get_service", kwargs)) or svc,
    )
    monkeypatch.setattr(boot, "render_db_status_banner", lambda: None)
    monkeypatch.setattr(
        boot,
        "render_analytics_contour_v2_page",
        lambda service: events.append(("render", service)),
    )

    boot.main()

    assert events[0] == "watchdog"
    assert events[1][0] == "get_service"
    assert events[1][1].get("load_companies") is True
    assert events[1][1].get("ping") is False
    assert events[2] == ("render", svc)


def test_get_service_skips_ping_by_default(monkeypatch) -> None:
    calls = {"health": 0}
    fake = SimpleNamespace(radar_db=object(), load_sync=lambda: True)

    class _Session(dict):
        def __getattr__(self, item):
            try:
                return self[item]
            except KeyError as exc:
                raise AttributeError(item) from exc

        def __setattr__(self, key, value):
            self[key] = value

        def get(self, key, default=None):
            return dict.get(self, key, default)

    class _St:
        session_state = _Session(service=fake, companies_data_loaded=True)

    monkeypatch.setattr(boot, "st", _St)
    monkeypatch.setattr(
        boot,
        "check_and_reconnect",
        lambda *a, **k: calls.__setitem__("health", calls["health"] + 1) or SimpleNamespace(),
    )
    monkeypatch.setattr(boot, "apply_health_to_session", lambda *a, **k: None)

    out = boot._get_service(load_companies=True, ping=False)
    assert out is fake
    assert calls["health"] == 0

    boot._get_service(load_companies=True, ping=True)
    assert calls["health"] == 1


def test_system_health_page_remains_snapshot_only() -> None:
    from src.services.system_health_config import (
        HISTORY_LOADED_ON_OVERVIEW,
        S7_SSH_CALLS_ON_UI_RERUN,
        UI_HARDWARE_PROBES,
    )

    assert UI_HARDWARE_PROBES == 0
    assert S7_SSH_CALLS_ON_UI_RERUN == 0
    assert HISTORY_LOADED_ON_OVERVIEW is False


def test_infrastructure_does_not_require_load_sync() -> None:
    assert requires_companies_load_sync("infrastructure") is False
    assert page_dependency("infrastructure") == PageDependency.OTHER
