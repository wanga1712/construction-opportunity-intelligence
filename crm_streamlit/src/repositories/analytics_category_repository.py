"""Read-only repository for analytics category options."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from psycopg2.extras import RealDictCursor


_CATEGORY_SQL = """
    SELECT DISTINCT crm_category FROM crm_procurements
    WHERE crm_category IS NOT NULL AND crm_category != ''
    ORDER BY crm_category
"""


class AnalyticsCategoryRepository:
    """Load category rows through an explicitly supplied connection factory."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def list_available_categories(self) -> list[str]:
        connection = self._connection_factory()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(_CATEGORY_SQL)
                return [row["crm_category"] for row in cursor.fetchall()]
        finally:
            connection.close()
