"""
Подключение исходного CRM-проекта (pythonProject89) через CRM_SOURCE_ROOT.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


def _load_own_env() -> None:
    """Load this project's own .env as the authoritative configuration.

    ``override=True`` is deliberate: CRM must never inherit database routing
    from a parent shell, from the sibling desktop project or from any other
    ambient environment.  There is deliberately NO cwd / ancestor
    auto-discovery fallback: the file is resolved from this module's location,
    never from the shell's working directory.
    """
    if _ENV_FILE.is_file():
        load_dotenv(_ENV_FILE, override=True)


_load_own_env()


def crm_env_file() -> Path:
    """Path of the single authoritative CRM configuration file.

    Public accessor for runtime components (e.g. the Second Pass worker) that
    must report which configuration source they use without re-implementing
    any env discovery of their own.
    """
    return _ENV_FILE


def setup_source_path() -> Path:
    """Добавить CRM_SOURCE_ROOT в sys.path и вернуть корень исходника."""
    root = os.environ.get("CRM_SOURCE_ROOT", "").strip()
    if not root:
        sibling = _PROJECT_ROOT.parent / "pythonProject89"
        if sibling.is_dir():
            root = str(sibling)
            os.environ["CRM_SOURCE_ROOT"] = root
    if not root:
        raise RuntimeError(
            "Переменная CRM_SOURCE_ROOT не задана. "
            "Укажите путь к pythonProject89 в .env (см. .env.example)."
        )
    source = Path(root).resolve()
    if not source.is_dir():
        raise RuntimeError(f"CRM_SOURCE_ROOT не найден: {source}")
    source_str = str(source)
    if source_str not in sys.path:
        sys.path.insert(0, source_str)
    _ensure_designer_analytics_display_name()
    # The sibling project is used ONLY as an import source.  Its .env is never
    # loaded, but sibling modules may run their own dotenv at import time, so
    # this project's authority over the environment is re-asserted afterwards.
    _load_own_env()
    return source


def _ensure_designer_analytics_display_name() -> None:
    """display_name на DesignerAnalytics — на случай старого кэша Streamlit/модуля."""
    import sys

    model_classes: list[type] = []
    for module in sys.modules.values():
        cls = getattr(module, "DesignerAnalytics", None)
        if isinstance(cls, type) and cls not in model_classes:
            model_classes.append(cls)

    if not model_classes:
        try:
            from modules.crm.analytics.analytics_models import DesignerAnalytics
        except ImportError:
            return
        model_classes.append(DesignerAnalytics)

    try:
        from modules.crm.analytics.company_display_name import display_company_name
    except ImportError:
        from src.ui.company_title import format_company_display_name as display_company_name

    for cls in model_classes:
        existing = getattr(cls, "display_name", None)
        if isinstance(existing, property):
            continue

        def _display_name(self, _fmt=display_company_name) -> str:
            return _fmt(
                getattr(self, "full_name", None),
                getattr(self, "legal_form", None),
            )

        cls.display_name = property(_display_name)
