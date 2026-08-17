from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import app as root_app
from src.ui import styles


def _exercise_main(monkeypatch, module):
    events = []
    monkeypatch.setattr(
        module.st,
        "set_page_config",
        lambda **_kwargs: events.append("set_page_config"),
    )
    monkeypatch.setattr(
        module, "inject_global_styles", lambda: events.append("styles")
    )
    monkeypatch.setattr(
        module,
        "run_app_bootstrap",
        lambda: events.append("app_bootstrap.main"),
    )

    module.main()
    return events


def test_production_bootstrap_injects_styles_once_in_order(monkeypatch):
    events = _exercise_main(monkeypatch, root_app)

    assert events == [
        "set_page_config",
        "styles",
        "app_bootstrap.main",
    ]
    assert events.count("styles") == 1


def test_production_style_error_propagates_before_routing(monkeypatch):
    events = []
    monkeypatch.setattr(
        root_app.st,
        "set_page_config",
        lambda **_kwargs: events.append("set_page_config"),
    )

    def fail_styles():
        events.append("styles")
        raise RuntimeError("style injection failed")

    monkeypatch.setattr(root_app, "inject_global_styles", fail_styles)
    monkeypatch.setattr(
        root_app,
        "run_app_bootstrap",
        lambda: events.append("unexpected_bootstrap"),
    )

    with pytest.raises(RuntimeError, match="style injection failed"):
        root_app.main()

    assert events == ["set_page_config", "styles"]


def test_global_css_sources_match_characterized_hashes():
    expected = {
        "styles.py": "f843254838c004e8c6bb071f61642f26a0c677d59e20b41d60a54962cd66397e",
        "styles_salesforce.py": "1439f4cbb3331181206f9b4310390cbb075e048d673ef0c35d234b31ac9d9c81",
    }
    actual = {}
    for name in expected:
        path = Path(styles.__file__).with_name(name)
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    assert actual == expected
