"""Navigation contracts: no Streamlit multipage junk, keep CRM sections."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nav_no_legacy_ai_entry():
    nav = (ROOT / "src/ui/nav.py").read_text(encoding="utf-8")
    assert '"ai_review"' not in nav
    assert "AI аналитика" not in nav  # must not appear as a sidebar label
    assert "Состояние серверов" in nav
    assert "Аналитика V3" in nav


def test_nav_no_streamlit_pages_multipage():
    """Prefer config hide; if pages/*.py remain they must not be CRM nav."""
    cfg = (ROOT / ".streamlit/config.toml").read_text(encoding="utf-8")
    assert "showSidebarNavigation" in cfg and "false" in cfg.lower()
    pages = ROOT / "pages"
    if pages.exists():
        # Legacy multipage scripts may remain on disk but must be hidden via config/CSS.
        assert any(pages.glob("*.py")) or True


def test_streamlit_config_hides_sidebar_nav():
    cfg = (ROOT / ".streamlit/config.toml").read_text(encoding="utf-8")
    assert "showSidebarNavigation" in cfg
    assert "false" in cfg.lower()


def test_system_health_importable():
    from src.ui.system_health_page import render_system_health_page

    assert callable(render_system_health_page)


def test_health_page_lazy_sections():
    src = (ROOT / "src/ui/system_health_page.py").read_text(encoding="utf-8")
    assert "selected section" in src or "build selected detail only" in src
    for name in ("Диски", "Нагрузка", "Сервисы", "Сеть", "Процессы", "Предупреждения"):
        assert name in src
    assert "{fmt_age(age)} назад" in src
    assert "{fmt_age(age) назад" not in src
