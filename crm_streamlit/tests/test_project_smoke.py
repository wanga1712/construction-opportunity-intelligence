from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".venv", "venv", "__pycache__", "tmp_remote_docs"}
EXCLUDED_PREFIXES = ("tmp_", "_tmp", "_nyx", "_remote")


def production_python_files() -> list[pathlib.Path]:
    return [
        path
        for path in ROOT.rglob("*.py")
        if not EXCLUDED_PARTS.intersection(path.parts)
        and not path.name.startswith(EXCLUDED_PREFIXES)
        and "tests" not in path.parts
    ]


class ProjectSmokeTests(unittest.TestCase):
    def test_all_production_modules_parse_as_python_313(self) -> None:
        for path in production_python_files():
            with self.subTest(path=path.relative_to(ROOT)):
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path), feature_version=(3, 13))

    def test_no_duplicate_definitions_in_same_scope(self) -> None:
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
        self.assertEqual([], duplicates, "Duplicate definitions: " + ", ".join(duplicates))

    def test_app_local_imports_resolve(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
        missing: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module or not node.module.startswith("src."):
                continue
            target = ROOT.joinpath(*node.module.split("."))
            if not target.with_suffix(".py").is_file() and not (target / "__init__.py").is_file():
                missing.append(node.module)
        self.assertEqual([], missing, "Missing local imports: " + ", ".join(missing))


if __name__ == "__main__":
    unittest.main()
