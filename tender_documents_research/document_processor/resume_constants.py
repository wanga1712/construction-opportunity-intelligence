"""Константы и настройки возобновления обработки PDF."""

from __future__ import annotations

import os

# Статусы processed_documents
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_PENDING_RESUME = "pending_resume"
STATUS_ERROR_MEMORY = "error_memory"
STATUS_SKIPPED = "skipped"

# Статусы, блокирующие завершение закупки
BLOCKING_FILE_STATUSES = (
    STATUS_PROCESSING,
    STATUS_PENDING_RESUME,
    STATUS_ERROR,
)


def max_resume_attempts() -> int:
    try:
        return max(1, int(os.getenv("MAX_RESUME_ATTEMPTS", "5")))
    except ValueError:
        return 5
