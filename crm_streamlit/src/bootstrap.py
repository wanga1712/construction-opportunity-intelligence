"""
Подключение исходного CRM-проекта (pythonProject89) через CRM_SOURCE_ROOT.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
else:
    load_dotenv()

# Fallback: те же ключи БД из десктопного проекта (не перезаписывает локальный .env)
_source_hint = os.environ.get("CRM_SOURCE_ROOT", "").strip()
if _source_hint:
    _source_env = Path(_source_hint) / ".env"
    if _source_env.is_file():
        load_dotenv(_source_env, override=False)


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
    # Load source project .env after resolving CRM_SOURCE_ROOT (module-level
    # load only runs when CRM_SOURCE_ROOT is already set in the environment).
    source_env = source / ".env"
    if source_env.is_file():
        load_dotenv(source_env, override=False)
    if source_str not in sys.path:
        sys.path.insert(0, source_str)
    _ensure_designer_analytics_display_name()
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
