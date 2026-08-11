from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from document_processor.backends.s13_persistence import S13V2TaskPersistenceService
from document_processor.backends.state_repository import (
    LegacyStateRepository,
    S13V2StateRepository,
)

ROOT = Path(__file__).resolve().parents[1] / "document_processor"


def test_pipeline_callers_use_injected_state_boundary() -> None:
    for relative in (
        "task_pipeline.py",
        "pdf_processor.py",
        "downloader.py",
        "daemon.py",
        "daemon_maintenance.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "downloader.registry" not in source
        assert "hasattr(self.downloader, 'registry')" not in source


def test_legacy_adapter_delegates_existing_registry() -> None:
    registry = MagicMock()
    registry.get_processed_status.return_value = ("completed",)
    adapter = LegacyStateRepository.__new__(LegacyStateRepository)
    adapter.registry = registry

    assert adapter.get_file_status(7, "source", "a.pdf", "hash") == ("completed",)
    adapter.finalize_processing_status(7, "source", "a.pdf", True)
    registry.get_processed_status.assert_called_once_with(7, "source", "a.pdf")
    registry.finalize_file_status.assert_called_once_with(
        7, "source", "a.pdf", True, None
    )


class FakeCursor:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[tuple] = []
        self.rowcount = 1
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.sql.append(" ".join(sql.split()))
        self.params.append(tuple(params))
        if "SELECT download_status, local_path" in sql:
            self._row = ("COMPLETED", "/data/tender-documents/a.pdf")

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class FakeConnection:
    closed = False

    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_s13_adapter_uses_only_local_document_files() -> None:
    conn = FakeConnection()
    adapter = S13V2StateRepository({})
    adapter._conn = conn
    adapter.ensure_download_file(
        11, 1282, "reestr_contract_44_fz", "https://source/doc", "abc", "a.pdf"
    )
    row = adapter.get_file_status(1282, "reestr_contract_44_fz", "a.pdf", "abc")
    adapter.finalize_download_status(
        1282, "reestr_contract_44_fz", "a.pdf", "abc", True,
        local_path="/data/tender-documents/a.pdf",
    )

    assert row == ("COMPLETED", "/data/tender-documents/a.pdf")
    executed = "\n".join(conn.cursor_instance.sql).lower()
    assert "document_files" in executed
    assert "processed_documents" not in executed
    assert "tender_monitor" not in executed


def test_completion_fails_closed_before_db_when_no_result_files() -> None:
    db = MagicMock()
    service = S13V2TaskPersistenceService(db)
    result = SimpleNamespace(files=[], queue_id=1)
    with pytest.raises(ValueError, match="at least one successfully processed"):
        service.persist_task_result(result)
    db.get_cursor.assert_not_called()


class PersistenceCursor(FakeCursor):
    def execute(self, sql, params=()):
        super().execute(sql, params)
        normalized = " ".join(sql.split())
        if "SELECT status" in normalized:
            self._row = ("PROCESSING",)
        elif "UPDATE document_files" in normalized:
            self._row = (101,)
        elif "INSERT INTO document_processing_results" in normalized:
            self._row = (201,)
        elif "SELECT COUNT(*) FROM document_processing_results" in normalized:
            self._row = (1,)
        else:
            self._row = None


class PersistenceConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__()
        self.cursor_instance = PersistenceCursor()


def test_successful_result_graph_marks_queue_completed() -> None:
    conn = PersistenceConnection()
    @contextmanager
    def _get_cursor(name):
        try:
            yield conn.cursor_instance
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    db = SimpleNamespace(get_cursor=_get_cursor)
    service = S13V2TaskPersistenceService(db)
    file_result = SimpleNamespace(
        file_name="a.pdf",
        status="COMPLETED",
        error_message=None,
        pages=1,
        sheets=0,
        rows=0,
        matches=[],
    )
    result = SimpleNamespace(
        queue_id=10,
        procurement_id=1282,
        files=[file_result],
        evidence=[],
        error_message=None,
        outcome="SUCCESS",
    )

    service.persist_task_result(result)

    executed = "\n".join(conn.cursor_instance.sql)
    assert "INSERT INTO document_processing_results" in executed
    assert "SET status = 'COMPLETED'" in executed
    assert conn.commits == 1


def test_no_link_terminal_semantics_are_explicit() -> None:
    daemon = (ROOT / "daemon.py").read_text(encoding="utf-8")
    queue = (ROOT / "backends" / "queue_repository.py").read_text(encoding="utf-8")
    assert "NO_RESEARCHABLE_DOCUMENT_LINKS" in daemon
    assert "mark_no_links" in daemon
    assert "status='NO_LINKS'" in queue
    assert "mark_completed(task_id, \"No downloadable files found\")" not in daemon
