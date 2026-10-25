from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from src.ui.page_deps import PageDependency, page_dependency
from src.services.queue_repository import LegacyQueueRepository

ROOT = Path(__file__).resolve().parents[1]


def load_audit_module():
    audit_path = ROOT / "scripts/audit_module_consistency_phase1.py"
    spec = importlib.util.spec_from_file_location("module_consistency_phase1_audit", audit_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_python(code: str, pythonpath: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(pythonpath)
    env.setdefault("CRM_SOURCE_ROOT", str(ROOT))
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_phase1_consistency_contract() -> None:
    assert sys.version_info[:2] == (3, 13)
    assert not (ROOT / "src/services/crm_procurements_repository.py").exists()
    assert page_dependency("procurement_card") == PageDependency.CRM_DB_ONLY

    module = load_audit_module()
    assert module.main() == 0


def test_manifest_audit_compares_both_directions_and_versions(tmp_path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["alpha==1", "pyproject-only==1"]

[project.optional-dependencies]
documents = []
learning = []
training = []
dev = []
""",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text(
        "alpha==2\nrequirements-only==1\n",
        encoding="utf-8",
    )
    for name in ("documents", "learning", "training", "dev"):
        (tmp_path / f"requirements-{name}.txt").write_text(
            "-r requirements.txt\n",
            encoding="utf-8",
        )

    module = load_audit_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    result = module.compare_manifests(module.load_profiles())["base"]

    assert result["pyproject_only"] == ["pyproject-only==1"]
    assert result["requirements_only"] == ["requirements-only==1"]
    assert result["version_mismatches"] == [
        {"package": "alpha", "pyproject": "==1", "requirements": "==2"}
    ]
    assert result["ok"] is False


def test_legacy_queue_repository_methods_from_project_root() -> None:
    class FakeDb:
        def __init__(self) -> None:
            self.calls = []

        def execute_query(self, alias, query, params=None, fetch=True):
            self.calls.append((alias, query, params, fetch))
            if "RETURNING id, contract_reg_number" in query:
                return [(11, "contract-11", "reestr_contract_44_fz", "open_active", 2, 90)]
            if "RETURNING id" in query:
                return [(1,), (2,)]
            return []

    db = FakeDb()
    repo = LegacyQueueRepository(db)

    assert repo.claim_batch(17, 1, ["open_active"]) == [
        {
            "id": 11,
            "contract_reg_number": "contract-11",
            "table_source": "reestr_contract_44_fz",
            "queue_lane": "open_active",
            "priority_class": 2,
            "priority_score": 90,
        }
    ]
    claim_query, claim_params = db.calls[0][1], db.calls[0][2]
    assert "UPDATE document_processing_queue" in claim_query
    assert "q.queue_lane IN (%s)" in claim_query
    assert claim_params == (17, 17, "open_active", 1)

    repo.mark_no_links(11, "no documents")
    assert repo.reset_stale_tasks(60, 17) == 2
    assert any("status='no_links'" in call[1] for call in db.calls)
    assert any("RETURNING id" in call[1] for call in db.calls)


def test_document_runtime_supports_project_and_production_import_modes() -> None:
    project_mode = """
from src.services.queue_repository import LegacyQueueRepository

class FakeDb:
    def __init__(self):
        self.calls = []

    def execute_query(self, alias, query, params=None, fetch=True):
        self.calls.append((alias, query, params, fetch))
        if "RETURNING id, contract_reg_number" in query:
            return [(11, "contract-11", "reestr_contract_44_fz", "open_active", 2, 90)]
        return [(1,), (2,)] if "RETURNING id" in query else []

db = FakeDb()
repo = LegacyQueueRepository(db)
assert repo.claim_batch(17, 1, ["open_active"])[0]["id"] == 11
repo.mark_no_links(11, "no documents")
assert repo.reset_stale_tasks(60, 17) == 2
print("PROJECT_MODE=OK")
"""
    project_result = run_python(project_mode, ROOT)
    assert project_result.returncode == 0, project_result.stderr
    assert "PROJECT_MODE=OK" in project_result.stdout

    production_mode = """
from document_processor.queue_manager import QueueManager
from database_work.database_connection import DatabaseManager

class Backend:
    queue = object()

manager = QueueManager(Backend(), object())
assert manager.repo is Backend.queue
assert DatabaseManager.__module__ == "database_work.database_connection"
print("PRODUCTION_MODE=OK")
"""
    production_result = run_python(
        production_mode,
        ROOT / "tender_documents_research",
    )
    assert production_result.returncode == 0, production_result.stderr
    assert "PRODUCTION_MODE=OK" in production_result.stdout
