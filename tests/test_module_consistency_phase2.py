from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_audit_module():
    path = ROOT / "scripts/audit_module_consistency_phase2.py"
    spec = importlib.util.spec_from_file_location("module_consistency_phase2_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_reconciliation_audit_module():
    path = ROOT / "scripts/production_reconciliation_audit.py"
    spec = importlib.util.spec_from_file_location(
        "production_reconciliation_audit_phase2",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_phase2_repository_contract() -> None:
    assert sys.version_info[:2] == (3, 13)
    assert load_audit_module().main() == 0


def test_duplicate_and_backup_audit_detect_artifacts(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tender_documents_research").mkdir()
    (tmp_path / "src/a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "src/b.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "src/file.py.backup").write_text("old\n", encoding="utf-8")
    (tmp_path / "src/test_hidden.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (tmp_path / "src/x.py.bak_local_20261025").write_text("old\n", encoding="utf-8")
    legacy_temp = tmp_path / "src/foo.tmp_path_issue"
    legacy_temp.mkdir()
    (legacy_temp / "x.py").write_text("old\n", encoding="utf-8")

    module = load_audit_module()

    assert module.exact_duplicate_groups(tmp_path) == [["src/a.py", "src/b.py"]]
    assert module.backup_artifacts(tmp_path) == [
        "src/file.py.backup",
        "src/foo.tmp_path_issue/x.py",
        "src/x.py.bak_local_20261025",
    ]
    assert module.undiscovered_test_copies(tmp_path) == ["src/test_hidden.py"]


def test_backup_audit_detects_empty_legacy_temp_directory(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tender_documents_research").mkdir()
    (tmp_path / "src/foo.tmp_path_issue").mkdir()

    assert load_audit_module().backup_artifacts(tmp_path) == [
        "src/foo.tmp_path_issue/"
    ]


def test_removed_service_app_is_stale_legacy_not_host_local() -> None:
    category, _section, _semantic = load_reconciliation_audit_module().drift_classification(
        "src/services/app.py",
        False,
    )

    assert category == "STALE_OLD_CODE"
