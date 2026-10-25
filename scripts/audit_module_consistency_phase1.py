#!/usr/bin/env python3
"""Read-only Phase 1 consistency audit for module/import/dependency contracts."""
from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("app.py", "nav.py", "src", "scripts", "tender_documents_research", "training", "pages")
SKIP_PARTS = {
    ".git", ".codex", ".codex_worktrees", "worktrees", "scratch", "__pycache__",
    ".venv", "venv", ".pytest_cache",
}

BASE_IMPORTS = {
    "streamlit", "pandas", "psycopg2", "dotenv", "loguru", "reportlab",
    "requests", "plotly", "psutil",
}
DOCUMENT_IMPORTS = {
    "openpyxl", "PyPDF2", "pypdf", "fitz", "pdfplumber", "docx", "pdf2image",
    "pytesseract", "rapidfuzz", "urllib3",
}
LEARNING_IMPORTS = {"catboost", "sklearn", "numpy", "scipy"}
TRAINING_IMPORTS = {"torch", "transformers", "peft", "bitsandbytes", "accelerate"}
DEV_IMPORTS = {"pytest"}
LEGACY_RUNTIME_IMPORTS = {"modules", "core", "config", "eis_requester"}
PROFILE_IMPORTS = {
    "base": BASE_IMPORTS,
    "documents": DOCUMENT_IMPORTS,
    "learning": LEARNING_IMPORTS,
    "training": TRAINING_IMPORTS,
    "dev": DEV_IMPORTS,
}
PACKAGE = {
    "psycopg2": "psycopg2-binary", "dotenv": "python-dotenv", "PyPDF2": "pypdf2",
    "pypdf": "pypdf", "fitz": "pymupdf", "docx": "python-docx",
    "sklearn": "scikit-learn",
}
PROFILE_FILES = {
    "base": "requirements.txt",
    "documents": "requirements-documents.txt",
    "learning": "requirements-learning.txt",
    "training": "requirements-training.txt",
    "dev": "requirements-dev.txt",
}


def py_files() -> list[Path]:
    files: list[Path] = []
    for rel in SCAN_ROOTS:
        path = ROOT / rel
        if path.is_file():
            files.append(path)
        elif path.exists():
            files.extend(path.rglob("*.py"))
    return sorted({
        p for p in files
        if not any(part in SKIP_PARTS or ".bak" in part or ".tmp" in part for part in p.parts)
    })


def canonical(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def parse_requirement_entry(value: str) -> tuple[str, str] | None:
    value = value.split(";", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)$", value)
    if not match:
        return None
    specifier = re.sub(r"\s+", "", match.group(2) or "")
    return canonical(match.group(1)), specifier


def parse_requirements(path: Path, seen: set[Path] | None = None) -> dict[str, str]:
    seen = seen or set()
    path = path.resolve()
    if path in seen or not path.is_file():
        return {}
    seen.add(path)
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            nested = line.split(maxsplit=1)[1].strip()
            result.update(parse_requirements(path.parent / nested, seen))
            continue
        if line.startswith("-"):
            continue
        parsed = parse_requirement_entry(line)
        if parsed is None:
            continue
        name, specifier = parsed
        result[name] = specifier
    return result


def load_profiles() -> dict[str, dict[str, str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    profile = {
        "base": dict(
            parsed
            for item in data["project"]["dependencies"]
            if (parsed := parse_requirement_entry(item)) is not None
        )
    }
    for name, values in data["project"].get("optional-dependencies", {}).items():
        profile[name] = dict(
            parsed
            for item in values
            if (parsed := parse_requirement_entry(item)) is not None
        )
    return profile


def compare_manifests(profiles: dict[str, dict[str, str]]) -> dict[str, dict]:
    mismatches = {}
    for name, filename in PROFILE_FILES.items():
        effective = dict(profiles.get("base", {}))
        if name != "base":
            effective.update(profiles.get(name, {}))
        requirements = parse_requirements(ROOT / filename)
        pyproject_only = sorted(
            f"{package}{effective[package]}"
            for package in effective.keys() - requirements.keys()
        )
        requirements_only = sorted(
            f"{package}{requirements[package]}"
            for package in requirements.keys() - effective.keys()
        )
        version_mismatches = [
            {
                "package": package,
                "pyproject": effective[package],
                "requirements": requirements[package],
            }
            for package in sorted(effective.keys() & requirements.keys())
            if effective[package] != requirements[package]
        ]
        mismatches[name] = {
            "pyproject_only": pyproject_only,
            "requirements_only": requirements_only,
            "version_mismatches": version_mismatches,
            "ok": not pyproject_only and not requirements_only and not version_mismatches,
        }
    return mismatches


def module_exists(module: str, resolution_roots: list[Path]) -> bool:
    if not module:
        return True
    rel = Path(*module.split("."))
    return any(
        (root / rel).with_suffix(".py").is_file()
        or (root / rel / "__init__.py").is_file()
        or ((root / rel).is_dir() and any((root / rel).glob("*.py")))
        for root in resolution_roots
    )


def audit_imports(files: list[Path], profiles: dict[str, set[str]]):
    scan_roots = {
        ROOT, ROOT / "scripts", ROOT / "src", ROOT / "training",
        ROOT / "tender_documents_research",
        ROOT / "tender_documents_research" / "document_processor",
    }
    scan_roots.update(path.parent for path in files)
    internal_tops = {"src", "scripts", "tender_documents_research"}
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_PARTS for part in p.parts):
            continue
        rel = p.relative_to(ROOT)
        if rel.parts:
            internal_tops.add(rel.parts[0].removesuffix(".py"))
        if (p.parent / "__init__.py").is_file():
            internal_tops.add(p.parent.name)
    external_by_profile = {
        name: {canonical(PACKAGE.get(mod, mod)) for mod in modules}
        for name, modules in PROFILE_IMPORTS.items()
    }
    all_declared = set().union(*external_by_profile.values())
    unresolved, undeclared = [], []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="ignore"))
        relpath = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = list(relpath.parent.parts)
                    for _ in range(node.level - 1):
                        if base:
                            base.pop()
                    module = ".".join(base + ([(node.module or "")] if node.module else []))
                    if not module_exists(module, [ROOT]):
                        unresolved.append(f"{relpath}:{node.lineno}:{'.' * node.level}{node.module or ''}")
                    continue
                module = node.module or ""
                top = module.split(".")[0]
                if not top or top in sys.stdlib_module_names:
                    continue
                if module_exists(module, list(scan_roots)):
                    continue
                if top in LEGACY_RUNTIME_IMPORTS:
                    continue
                if top in internal_tops:
                    if not module_exists(module, list(scan_roots)):
                        unresolved.append(f"{relpath}:{node.lineno}:{module}")
                    continue
                package = canonical(PACKAGE.get(top, top))
                if package not in all_declared:
                    undeclared.append(f"{relpath}:{node.lineno}:{top}->{package}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if (
                        top in sys.stdlib_module_names
                        or top in LEGACY_RUNTIME_IMPORTS
                        or module_exists(alias.name, list(scan_roots))
                        or top in internal_tops
                    ):
                        continue
                    package = canonical(PACKAGE.get(top, top))
                    if package not in all_declared:
                        undeclared.append(f"{relpath}:{node.lineno}:{top}->{package}")
    return sorted(set(unresolved)), sorted(set(undeclared))


def audit_routes():
    deps_path = ROOT / "src/ui/page_deps.py"
    app_path = ROOT / "src/ui/app_bootstrap.py"
    deps_tree = ast.parse(deps_path.read_text(encoding="utf-8"))
    dependency_keys = set()
    for node in deps_tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "PAGE_DEPENDENCY" and isinstance(node.value, ast.Dict):
                dependency_keys = {
                    key.value for key in node.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
    app_tree = ast.parse(app_path.read_text(encoding="utf-8"))
    handled = set()
    for node in ast.walk(app_tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_render_page":
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Compare)
                    and isinstance(child.left, ast.Name)
                    and child.left.id == "page"
                    and isinstance(child.comparators[0], ast.Constant)
                    and isinstance(child.comparators[0].value, str)
                ):
                    handled.add(child.comparators[0].value)
    return sorted(handled), sorted(handled - dependency_keys)


def main() -> int:
    files = py_files()
    profiles = load_profiles()
    manifest_mismatches = compare_manifests(profiles)
    unresolved, undeclared = audit_imports(files, profiles)
    handled, missing_deps = audit_routes()
    profile_imports = {
        name: sorted(canonical(PACKAGE.get(mod, mod)) for mod in modules
                     if canonical(PACKAGE.get(mod, mod)) not in profiles.get(name, {}))
        for name, modules in PROFILE_IMPORTS.items()
    }
    py_ok = sys.version_info[:2] == (3, 13)
    result = {
        "python_runtime": sys.version.split()[0],
        "python_files": len(files),
        "unresolved_internal_imports": unresolved,
        "handled_routes": handled,
        "missing_route_dependencies": missing_deps,
        "undeclared_direct_imports": undeclared,
        "profile_import_gaps": profile_imports,
        "profile_manifests": manifest_mismatches,
        "acceptance": {
            "PROFILE_MANIFEST_GAPS": sum(
                len(item["pyproject_only"])
                + len(item["requirements_only"])
                + len(item["version_mismatches"])
                for item in manifest_mismatches.values()
            ),
            "UNRESOLVED_INTERNAL_IMPORTS": len(unresolved),
            "ALL_HANDLED_ROUTES_HAVE_EXPLICIT_DEPENDENCY": not missing_deps,
            "DIRECT_IMPORTS_DECLARED_IN_PROFILE": (
                not undeclared
                and not any(profile_imports.values())
                and all(item["ok"] for item in manifest_mismatches.values())
            ),
            "PYTHON_RUNTIME_3_13": py_ok,
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if (
        py_ok and not unresolved and not missing_deps and not undeclared
        and not any(profile_imports.values())
        and all(item["ok"] for item in manifest_mismatches.values())
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
