#!/usr/bin/env python3
"""Read-only Phase 2 duplicate-authority and repository-hygiene audit."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOTS = (Path("src"), Path("tender_documents_research"))
SKIP_PARTS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "scratch", "tests",
}
LEGACY_AUTHORITIES = (
    Path("nav.py"),
    Path("src/services/app.py"),
    Path("src/services/nav.py"),
    Path("src/services/analytics_contour_v2_page.py"),
    Path("src/services/card_compact.py"),
    Path("src/services/card_tabs_ai.py"),
    Path("src/services/card_tabs_medals.py"),
    Path("src/services/crm_profiles_page.py"),
    Path("src/services/tabs.py"),
    Path("src/ui/product_subcategories_service.py"),
)
BACKUP_SUFFIXES = (".bak", ".backup", ".orig")
LEGACY_TEMP_SUFFIX = ".tmp_path_issue"


def runtime_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for relative_root in RUNTIME_ROOTS:
        base = root / relative_root
        if not base.exists():
            continue
        files.extend(
            path
            for path in base.rglob("*.py")
            if path.name != "__init__.py"
            and not any(part in SKIP_PARTS for part in path.parts)
        )
    return sorted(files)


def exact_duplicate_groups(root: Path) -> list[list[str]]:
    by_digest: dict[str, list[str]] = defaultdict(list)
    for path in runtime_python_files(root):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        by_digest[digest].append(path.relative_to(root).as_posix())
    return sorted(
        (sorted(paths) for paths in by_digest.values() if len(paths) > 1),
        key=lambda paths: paths[0],
    )


def undiscovered_test_copies(root: Path) -> list[str]:
    src = root / "src"
    if not src.exists():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in src.rglob("test_*.py")
        if not any(part in SKIP_PARTS for part in path.parts)
    )


def backup_artifacts(root: Path) -> list[str]:
    result: set[str] = set()
    for relative_root in RUNTIME_ROOTS:
        base = root / relative_root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            relative = path.relative_to(root)
            in_legacy_temp = any(
                part.endswith(LEGACY_TEMP_SUFFIX)
                for part in relative.parts
            )
            if path.is_file():
                name = path.name.lower()
                is_backup = (
                    name.endswith(BACKUP_SUFFIXES)
                    or ".bak_" in name
                    or ".bak." in name
                )
                if is_backup or in_legacy_temp:
                    result.add(relative.as_posix())
            elif (
                path.is_dir()
                and path.name.endswith(LEGACY_TEMP_SUFFIX)
                and not any(path.iterdir())
            ):
                result.add(relative.as_posix() + "/")
    return sorted(result)


def main() -> int:
    duplicates = exact_duplicate_groups(ROOT)
    missing_authorities = [
        path.as_posix()
        for path in LEGACY_AUTHORITIES
        if (ROOT / path).exists()
    ]
    hidden_tests = undiscovered_test_copies(ROOT)
    backups = backup_artifacts(ROOT)

    app_source = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    bootstrap_source = (ROOT / "src/ui/app_bootstrap.py").read_text(encoding="utf-8-sig")
    product_service = ROOT / "src/services/product_subcategories_service.py"

    acceptance = {
        "EXACT_DUPLICATE_RUNTIME_GROUPS": len(duplicates),
        "CANONICAL_APP_AUTHORITY": (
            "from src.ui.app_bootstrap import main" in app_source
            and "from src.ui.nav import render_sidebar_nav" in bootstrap_source
        ),
        "CANONICAL_NAV_AUTHORITY": "src/ui/nav.py",
        "LEGACY_AUTHORITY_FILES": missing_authorities,
        "UI_CODE_IN_SERVICES_DUPLICATION": len(
            [
                path for path in missing_authorities
                if path.startswith("src/services/")
            ]
        ),
        "PRODUCT_SUBCATEGORY_SCHEMA_AUTHORITY": (
            "src/services/product_subcategories_service.py"
            if product_service.is_file()
            else None
        ),
        "UNDISCOVERED_TEST_COPIES": len(hidden_tests),
        "BACKUP_ARTIFACTS": len(backups),
        "PYTHON_RUNTIME_3_13": sys.version_info[:2] == (3, 13),
    }
    result = {
        "acceptance": acceptance,
        "duplicate_groups": duplicates,
        "hidden_tests": hidden_tests,
        "backup_artifacts": backups,
        "python_runtime": sys.version.split()[0],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if (
        not duplicates
        and not missing_authorities
        and not hidden_tests
        and not backups
        and acceptance["CANONICAL_APP_AUTHORITY"]
        and product_service.is_file()
        and sys.version_info[:2] == (3, 13)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
