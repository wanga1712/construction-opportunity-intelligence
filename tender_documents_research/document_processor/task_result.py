"""Результат обработки одной закупки."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class TaskProcessResult:
    """Итог обработки задачи: можно ли закрывать закупку."""

    pending_resume_files: List[str] = field(default_factory=list)
    error_memory_files: List[str] = field(default_factory=list)
    retryable_error_files: List[str] = field(default_factory=list)

    @property
    def can_complete(self) -> bool:
        return not (
            self.pending_resume_files
            or self.error_memory_files
            or self.retryable_error_files
        )

    @property
    def needs_requeue(self) -> bool:
        return bool(self.pending_resume_files)

    def summary_message(self) -> str:
        parts: List[str] = []
        if self.pending_resume_files:
            parts.append(
                f"pending_resume: {len(self.pending_resume_files)} файл(ов)"
            )
        if self.error_memory_files:
            parts.append(
                f"error_memory: {len(self.error_memory_files)} файл(ов)"
            )
        if self.retryable_error_files:
            parts.append(
                f"retryable_error: {len(self.retryable_error_files)} файл(ов)"
            )
        return "; ".join(parts) if parts else "ok"
