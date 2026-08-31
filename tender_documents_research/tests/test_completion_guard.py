from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _reset_package() -> None:
    for name in list(sys.modules):
        if name == "document_processor" or name.startswith("document_processor."):
            sys.modules.pop(name)
    package = types.ModuleType("document_processor")
    package.__path__ = [str(PROJECT_ROOT / "document_processor")]
    sys.modules["document_processor"] = package


def _load_module(name: str):
    _reset_package()
    return importlib.import_module(f"document_processor.{name}")


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("processing", "document_non_terminal"),
        ("pending", "document_non_terminal"),
        ("pending_resume", "document_non_terminal"),
        ("partial", "document_partial"),
        ("error_memory", "document_error_memory"),
        ("error", "document_retryable_error"),
        ("failed", "document_retryable_error"),
        ("retry", "document_retryable_error"),
        ("retry_wait", "document_retryable_error"),
        ("new_status", "document_unknown_status"),
        ("skipped", "document_non_terminal"),
    ],
)
def test_guard_blocks_every_non_success_status(status: str, reason: str) -> None:
    guard = _load_module("completion_guard")
    decision = guard.evaluate_completion_guard([("a.pdf", status)])
    assert decision.allowed is False
    assert reason in decision.blocking_reasons
    assert decision.policy_version == "temporary_completion_guard_v1"


def test_only_completed_is_successful() -> None:
    guard = _load_module("completion_guard")
    decision = guard.evaluate_completion_guard(
        [("a.pdf", "completed"), ("b.docx", "completed")]
    )
    assert guard.SUCCESSFUL_FILE_STATUSES == frozenset({"completed"})
    assert decision.allowed is True
    assert decision.blocking_reasons == ()
    assert decision.observed_statuses == ("completed", "completed")


def test_empty_malformed_and_incomplete_extraction_fail_closed() -> None:
    guard = _load_module("completion_guard")
    empty = guard.evaluate_completion_guard([])
    malformed = guard.evaluate_completion_guard([("broken",)])
    incomplete = guard.evaluate_completion_guard(
        [("a.pdf", "completed")], extraction_complete=False
    )
    assert empty.blocking_reasons == ("no_documents", "extraction_incomplete")
    assert "document_unknown_status" in malformed.blocking_reasons
    assert incomplete.blocking_reasons == ("extraction_incomplete",)


def test_status_read_error_and_retryable_flag_fail_closed() -> None:
    guard = _load_module("completion_guard")
    decision = guard.evaluate_completion_guard(
        [("a.pdf", "completed")],
        status_read_failed=True,
        retryable_failure=True,
    )
    assert decision.allowed is False
    assert decision.blocking_reasons == (
        "status_read_failed",
        "document_retryable_error",
    )


def test_registry_strict_read_propagates_failure(monkeypatch) -> None:
    database_module = types.ModuleType("database_work.database_connection")
    database_module.DatabaseManager = object
    monkeypatch.setitem(
        sys.modules, "database_work.database_connection", database_module
    )
    _reset_package()
    locator_module = types.ModuleType("document_processor.registry_contract_locator")
    locator_module.RegistryContractLocator = object
    monkeypatch.setitem(
        sys.modules, "document_processor.registry_contract_locator", locator_module
    )
    registry_module = importlib.import_module("document_processor.processed_registry")

    manager = registry_module.ProcessedRegistry.__new__(
        registry_module.ProcessedRegistry
    )
    manager.db_alias = "test"
    manager.db = types.SimpleNamespace(
        execute_query=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("read failed")
        )
    )
    manager.logger = types.SimpleNamespace(error=lambda *args, **kwargs: None)

    assert manager.list_file_statuses(1, "table") == []
    with pytest.raises(RuntimeError, match="read failed"):
        manager.list_file_statuses(1, "table", raise_on_error=True)


def test_compatibility_wrapper_delegates_canonical_policy() -> None:
    completion = _load_module("task_completion")
    assert completion.can_complete_tender_files([("a.pdf", "completed")]) is True
    assert completion.can_complete_tender_files([("a.pdf", "error_memory")]) is False
    assert completion.can_complete_tender_files([]) is False


class FakeQueue:
    def __init__(self) -> None:
        self.completed: list[tuple] = []
        self.errors: list[tuple] = []
        self.requeues: list[tuple] = []

    def mark_completed(self, task_id: int, **facts):
        self.completed.append((task_id, facts))
        guard = importlib.import_module("document_processor.completion_guard")
        return guard.evaluate_completion_guard(
            facts["status_rows"],
            retryable_failure=facts["retryable_failure"],
            status_read_failed=facts["status_read_failed"],
            task_eligible=facts["task_eligible"],
        )

    def mark_error(self, task_id: int, message: str) -> None:
        self.errors.append((task_id, message))

    def mark_requeue_pending(self, task_id: int, message: str) -> None:
        self.requeues.append((task_id, message))


def test_daemon_application_path_never_calls_completed_when_blocked() -> None:
    result_module = _load_module("task_result")
    queue = FakeQueue()
    result = result_module.TaskProcessResult(error_memory_files=["a.pdf"])
    decision = result.apply_completion(queue, 41, [("a.pdf", "error_memory")])
    assert decision.allowed is False
    assert queue.completed == []
    assert queue.errors == [(41, "error_memory: 1 файл(ов)")]


def test_daemon_application_path_preserves_success() -> None:
    result_module = _load_module("task_result")
    queue = FakeQueue()
    result = result_module.TaskProcessResult()
    decision = result.apply_completion(queue, 42, [("a.pdf", "completed")])
    assert decision.allowed is True
    assert len(queue.completed) == 1
    assert queue.errors == []
    assert queue.requeues == []


def _load_queue_manager(monkeypatch):
    database_module = types.ModuleType("database_work.database_connection")
    database_module.DatabaseManager = object
    monkeypatch.setitem(
        sys.modules, "database_work.database_connection", database_module
    )
    logger_module = types.ModuleType("utils.logger_config")
    logger_module.get_logger = lambda: None
    monkeypatch.setitem(sys.modules, "utils.logger_config", logger_module)
    return _load_module("queue_manager")


def test_final_boundary_blocks_direct_call_without_facts(monkeypatch) -> None:
    queue_module = _load_queue_manager(monkeypatch)
    calls: list[tuple] = []
    manager = queue_module.QueueManager.__new__(queue_module.QueueManager)
    manager.db = types.SimpleNamespace(
        execute_query=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    decision = manager.mark_completed(43)
    assert decision.allowed is False
    assert "no_documents" in decision.blocking_reasons
    assert calls == []


def test_final_boundary_runs_update_only_for_success_and_is_idempotent(
    monkeypatch,
) -> None:
    queue_module = _load_queue_manager(monkeypatch)
    calls: list[tuple] = []
    manager = queue_module.QueueManager.__new__(queue_module.QueueManager)
    manager.db = types.SimpleNamespace(
        execute_query=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    for _ in range(2):
        decision = manager.mark_completed(44, status_rows=[("a.pdf", "completed")])
        assert decision.allowed is True
    assert len(calls) == 2
    assert all("SET status = 'completed'" in call[0][0] for call in calls)


def test_no_links_remains_separate_and_guard_claims_no_future_invariants() -> None:
    daemon_source = (PROJECT_ROOT / "document_processor" / "daemon.py").read_text()
    guard_source = (
        PROJECT_ROOT / "document_processor" / "completion_guard.py"
    ).read_text()
    assert "mark_no_links" in daemon_source
    assert "crm_persisted" not in guard_source
    assert "fencing" not in guard_source
    assert "receipt" not in guard_source
