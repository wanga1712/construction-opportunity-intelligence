from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.repositories import analytics_contour_repository as repository_module


def _repository_with_fake_objects_service():
    objects_service = MagicMock()
    repository = repository_module.AnalyticsContourRepository(objects_service)
    assert repository.objects_service is objects_service
    return repository, objects_service


def test_repository_delegates_inputs_and_preserves_return_shapes() -> None:
    repository, objects_service = _repository_with_fake_objects_service()
    objects_service.load_sync.return_value = True
    objects_service.all_objects.return_value = [{"key": "one"}]
    objects_service.get_item_by_key.return_value = {"key": "one"}
    objects_service.dynamic_product_groups.return_value = [("flooring", "Полы")]
    objects_service.available_regions.return_value = [(77, "Москва")]
    objects_service.index_meta.return_value = {"row_count": 1}

    assert repository.load("школа") is True
    assert repository.items() == [{"key": "one"}]
    assert repository.get_item("one") == {"key": "one"}
    assert repository.groups(include_computers=True) == [("flooring", "Полы")]
    assert repository.regions() == [(77, "Москва")]
    assert repository.index_meta() == {"row_count": 1}

    objects_service.load_sync.assert_called_once_with(search_query="школа")
    objects_service.get_item_by_key.assert_called_once_with("one")
    objects_service.dynamic_product_groups.assert_called_once_with(
        include_computers=True
    )


def test_repository_preserves_empty_results() -> None:
    repository, objects_service = _repository_with_fake_objects_service()
    objects_service.all_objects.return_value = []
    objects_service.get_item_by_key.return_value = None
    objects_service.dynamic_product_groups.return_value = []
    objects_service.available_regions.return_value = []
    objects_service.index_meta.return_value = {}

    assert repository.items() == []
    assert repository.get_item("missing") is None
    assert repository.groups() == []
    assert repository.regions() == []
    assert repository.index_meta() == {}


def test_repository_preserves_expected_collaborator_error() -> None:
    repository, objects_service = _repository_with_fake_objects_service()
    objects_service.load_sync.side_effect = RuntimeError("index unavailable")

    with pytest.raises(RuntimeError, match="index unavailable"):
        repository.load("query")
