"""Результат обработки одной закупки."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .completion_guard import CompletionGuardDecision, evaluate_completion_guard


@dataclass
class TaskProcessResult:
    """Итог обработки задачи: можно ли закрывать закупку."""

    pending_resume_files: list[str] = field(default_factory=list)
    error_memory_files: list[str] = field(default_factory=list)
    retryable_error_files: list[str] = field(default_factory=list)

    @property
    def can_complete(self) -> bool:
        status = "completed"
        if self.error_memory_files:
            status = "error_memory"
        elif self.pending_resume_files:
            status = "pending_resume"
        elif self.retryable_error_files:
            status = "error"
        return evaluate_completion_guard(
            [("task_result", status)],
            retryable_failure=bool(self.retryable_error_files),
        ).allowed

    def completion_status_rows(self, status_rows: list[tuple]) -> list[tuple]:
        rows = list(status_rows)
        rows.extend((name, "pending_resume") for name in self.pending_resume_files)
        rows.extend((name, "error_memory") for name in self.error_memory_files)
        rows.extend((name, "error") for name in self.retryable_error_files)
        return rows

    def completion_decision(
        self,
        status_rows: list[tuple],
        *,
        status_read_failed: bool = False,
        task_eligible: bool = True,
    ) -> CompletionGuardDecision:
        return evaluate_completion_guard(
            self.completion_status_rows(status_rows),
            retryable_failure=bool(self.retryable_error_files),
            status_read_failed=status_read_failed,
            task_eligible=task_eligible,
        )

    def apply_completion(
        self,
        queue_manager: Any,
        task_id: int,
        status_rows: list[tuple],
        *,
        status_read_failed: bool = False,
        task_eligible: bool = True,
    ) -> CompletionGuardDecision:
        decision = self.completion_decision(
            status_rows,
            status_read_failed=status_read_failed,
            task_eligible=task_eligible,
        )
        if not decision.allowed:
            terminal_error_reasons = {
                "document_error_memory",
                "document_retryable_error",
                "document_unknown_status",
                "status_read_failed",
                "task_not_eligible",
            }
            message = self.summary_message() or "; ".join(decision.blocking_reasons)
            if terminal_error_reasons.intersection(decision.blocking_reasons):
                queue_manager.mark_error(task_id, message)
            else:
                queue_manager.mark_requeue_pending(task_id, message)
            return decision

        return queue_manager.mark_completed(
            task_id,
            status_rows=self.completion_status_rows(status_rows),
            retryable_failure=bool(self.retryable_error_files),
            status_read_failed=status_read_failed,
            task_eligible=task_eligible,
        )

    @property
    def needs_requeue(self) -> bool:
        return bool(self.pending_resume_files)

    def summary_message(self) -> str:
        parts: list[str] = []
        if self.pending_resume_files:
            parts.append(f"pending_resume: {len(self.pending_resume_files)} файл(ов)")
        if self.error_memory_files:
            parts.append(f"error_memory: {len(self.error_memory_files)} файл(ов)")
        if self.retryable_error_files:
            parts.append(f"retryable_error: {len(self.retryable_error_files)} файл(ов)")
        return "; ".join(parts) if parts else "ok"
