"""Unified taxonomy repository exports maintaining full backward compatibility."""

from __future__ import annotations

from src.repositories.taxonomy_base import (
    DEFAULT_TAXONOMY_STORAGE_PATH,
    TaxonomyRepositoryProtocol,
)
from src.repositories.taxonomy_json import JsonTaxonomyRepository
from src.repositories.taxonomy_postgres import PostgresTaxonomyRepository

TaxonomyRepository = JsonTaxonomyRepository

__all__ = [
    "DEFAULT_TAXONOMY_STORAGE_PATH",
    "TaxonomyRepositoryProtocol",
    "JsonTaxonomyRepository",
    "PostgresTaxonomyRepository",
    "TaxonomyRepository",
]
