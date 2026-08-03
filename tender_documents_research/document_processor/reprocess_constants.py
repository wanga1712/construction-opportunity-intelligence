"""Маркеры повторной обработки в очереди."""

REPROCESS_ENRICH_PREFIX = "reprocess_enrich:"


def is_reprocess_enrich_message(message: str | None) -> bool:
    return bool(message) and message.startswith(REPROCESS_ENRICH_PREFIX)
