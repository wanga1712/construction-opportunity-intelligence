from __future__ import annotations

import compileall
import importlib
import sys
from pathlib import Path

import pytest

from eis_ingestion.tests._walk import walk

REPO = Path(__file__).resolve().parents[2]
S7 = REPO / "eis_ingestion" / "s7_forward"
S13 = REPO / "eis_ingestion" / "s13_backfill"


def test_s7_import_closure_complete():
    files, missing = walk(S7)
    assert missing == [], missing
    assert "main.py" in files
    assert "utils/xml_extractor.py" in files
    assert "orchestration/monitoring_service.py" in files


def test_s13_import_closure_complete():
    files, missing = walk(S13)
    assert missing == [], missing
    assert "main.py" in files
    assert "utils/xml_extractor.py" in files


def test_s7_and_s13_compile():
    assert compileall.compile_dir(str(S7), quiet=1, force=True)
    assert compileall.compile_dir(str(S13), quiet=1, force=True)


def test_s7_main_import_smoke(monkeypatch, tmp_path):
    pytest.importorskip("loguru")
    pytest.importorskip("requests")
    monkeypatch.setenv("TENDERMONITOR_LOG_DIR", str(tmp_path))
    monkeypatch.chdir(S7)
    sys.path.insert(0, str(S7))
    for name in list(sys.modules):
        if name == "config" or name.startswith("config.") or name in {
            "main",
            "eis_requester",
            "orchestration",
            "orchestration.monitoring_service",
        }:
            sys.modules.pop(name, None)
    module = importlib.import_module("main")
    assert hasattr(module, "save_processed_date")
    assert callable(module.mark_region_processed)


def test_s13_main_import_smoke(monkeypatch, tmp_path):
    pytest.importorskip("loguru")
    pytest.importorskip("requests")
    monkeypatch.setenv("TENDERMONITOR_LOG_DIR", str(tmp_path))
    monkeypatch.chdir(S13)
    sys.path.insert(0, str(S13))
    for name in list(sys.modules):
        if name == "config" or name.startswith("config.") or name in {
            "main",
            "eis_requester",
            "orchestration",
            "orchestration.monitoring_service",
        }:
            sys.modules.pop(name, None)
    module = importlib.import_module("main")
    assert callable(module.mark_region_processed)


def test_locator_trees_are_not_unified():
    s7 = (S7 / "database_work" / "contract_registry_locator.py").read_bytes()
    s13 = (S13 / "database_work" / "contract_registry_locator.py").read_bytes()
    assert s7 != s13
