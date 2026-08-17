from __future__ import annotations

import ast
import importlib
import pathlib
import pkgutil
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


def production_python_files() -> list[pathlib.Path]:
    return [
        path
        for base in (ROOT / "src",)
        for path in base.rglob("*.py")
        if not any(".py." in part or part.startswith(("tmp_", "_tmp")) for part in path.parts)
    ] + [ROOT / "app.py"]


def test_app_and_all_src_modules_import() -> None:
    importlib.import_module("app")
    src = importlib.import_module("src")
    modules = [info.name for info in pkgutil.walk_packages(src.__path__, prefix="src.")]
    for module_name in modules:
        importlib.import_module(module_name)


def test_ai_review_page_import_and_failure_call() -> None:
    page = importlib.import_module("src.ui.ai_review_page")
    render = page.render_ai_review_page
    objects_service = MagicMock()
    objects_service.load_sync.return_value = False
    objects_service.last_error = "test load failure"

    with (
        patch.object(page, "get_objects_service", return_value=objects_service),
        patch.object(page.st, "session_state", {}),
        patch.object(page.st, "title"),
        patch.object(page.st, "caption"),
        patch.object(page.st, "spinner", return_value=MagicMock()),
        patch.object(page.st, "error") as error,
    ):
        render.__wrapped__(object())

    objects_service.load_sync.assert_called_once_with(search_query="")
    error.assert_called_once_with("test load failure")


def test_no_duplicate_definitions_in_same_scope() -> None:
    duplicates: list[str] = []
    for path in production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        scopes = [("module", tree.body)] + [
            (node.name, node.body) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        ]
        for scope_name, body in scopes:
            seen: set[str] = set()
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        duplicates.append(f"{path.relative_to(ROOT)}:{node.lineno} {scope_name}.{node.name}")
                    seen.add(node.name)
    assert duplicates == []


def test_dynamic_product_groups_preserves_offline_and_online_behavior() -> None:
    module = importlib.import_module("src.services.objects_service")
    service = module.ObjectsService.__new__(module.ObjectsService)
    service.crm_db = None

    offline = service.dynamic_product_groups()
    assert offline
    assert all(code != "computers" for code, _ in offline)
    assert ("computers", "Компьютеры / ИТ") in service.dynamic_product_groups(
        include_computers=True
    )

    service.crm_db = SimpleNamespace(is_offline_mode=lambda: False)
    rows = [SimpleNamespace(code="flooring", name="Полы"), SimpleNamespace(code="computers", name="ИТ")]
    profiled = MagicMock()
    profiled.product_groups.return_value = rows
    with patch.object(module, "ProfiledSearchService", return_value=profiled):
        assert service.dynamic_product_groups() == [("flooring", "Полы")]
        assert service.dynamic_product_groups(include_computers=True) == [
            ("flooring", "Полы"),
            ("computers", "ИТ"),
        ]
