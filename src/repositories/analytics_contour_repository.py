"""Репозиторий данных для нового аналитического контура."""
from __future__ import annotations

from src.services.companies_service import CompaniesService
from src.ui.session_deps import get_objects_service


class AnalyticsContourRepository:
    """Тонкий доступ к данным без UI-логики."""

    def __init__(self, service: CompaniesService) -> None:
        self._service = service
        self._objects_service = get_objects_service(service)

    @property
    def objects_service(self):
        return self._objects_service

    def load(self, search_query: str = "") -> bool:
        return self._objects_service.load_sync(search_query=search_query)

    def items(self):
        return self._objects_service.all_objects()

    def get_item(self, object_key: str):
        return self._objects_service.get_item_by_key(object_key)

    def groups(self, include_computers: bool = False):
        return self._objects_service.dynamic_product_groups(
            include_computers=include_computers
        )

    def regions(self):
        return self._objects_service.available_regions()

    def index_meta(self):
        return self._objects_service.index_meta()
