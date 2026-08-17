"""Application boundary for analytics category options."""
from __future__ import annotations

from src.repositories.analytics_category_repository import AnalyticsCategoryRepository


def list_available_categories(repository: AnalyticsCategoryRepository) -> list[str]:
    """Preserve the existing empty fallback for database failures."""
    try:
        return repository.list_available_categories()
    except Exception:
        return []
