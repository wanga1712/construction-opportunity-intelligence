"""Fail-closed policy for the temporary document-task completion boundary."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

POLICY_VERSION = "temporary_completion_guard_v1"
SUCCESSFUL_FILE_STATUSES = frozenset({"completed"})

_KNOWN_NON_TERMINAL = frozenset({"processing", "pending", "pending_resume", "skipped"})
_KNOWN_RETRYABLE = frozenset({"error", "failed", "retry", "retry_wait"})


@dataclass(frozen=True)
class CompletionGuardDecision:
    allowed: bool
    blocking_reasons: tuple[str, ...]
    observed_statuses: tuple[str, ...]
    policy_version: str = POLICY_VERSION


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def evaluate_completion_guard(
    status_rows: Sequence[tuple[object, object]] | None,
    *,
    extraction_complete: bool | None = None,
    retryable_failure: bool = False,
    status_read_failed: bool = False,
    task_eligible: bool = True,
    already_completed: bool = False,
) -> CompletionGuardDecision:
    """Allow completion only when every observed file is explicitly successful."""
    reasons: list[str] = []
    statuses: list[str] = []

    if already_completed:
        _append_reason(reasons, "already_completed")
    if not task_eligible:
        _append_reason(reasons, "task_not_eligible")
    if status_read_failed:
        _append_reason(reasons, "status_read_failed")
    if retryable_failure:
        _append_reason(reasons, "document_retryable_error")

    rows: Iterable[tuple[object, object]] = status_rows or ()
    malformed = False
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            malformed = True
            statuses.append("<malformed>")
            continue
        raw_status = row[1]
        if not isinstance(raw_status, str) or not raw_status.strip():
            malformed = True
            statuses.append("<malformed>")
            continue
        status = raw_status.strip().lower()
        statuses.append(status)
        if status in SUCCESSFUL_FILE_STATUSES:
            continue
        if status == "error_memory":
            _append_reason(reasons, "document_error_memory")
        elif status == "partial":
            _append_reason(reasons, "document_partial")
        elif status in _KNOWN_RETRYABLE:
            _append_reason(reasons, "document_retryable_error")
        elif status in _KNOWN_NON_TERMINAL:
            _append_reason(reasons, "document_non_terminal")
        else:
            _append_reason(reasons, "document_unknown_status")

    if malformed:
        _append_reason(reasons, "document_unknown_status")
    if not statuses:
        _append_reason(reasons, "no_documents")
    extraction_proven = (
        bool(statuses)
        and not malformed
        and all(status in SUCCESSFUL_FILE_STATUSES for status in statuses)
        if extraction_complete is None
        else extraction_complete
    )
    if not extraction_proven:
        _append_reason(reasons, "extraction_incomplete")

    return CompletionGuardDecision(
        allowed=not reasons,
        blocking_reasons=tuple(reasons),
        observed_statuses=tuple(statuses),
    )
