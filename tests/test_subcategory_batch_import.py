"""Regression test: annotation_card can import load_subcategories_for_categories."""
import importlib


def test_load_subcategories_for_categories_importable():
    mod = importlib.import_module("src.services.expert_annotation_service")
    fn = getattr(mod, "load_subcategories_for_categories", None)
    assert fn is not None, "load_subcategories_for_categories must be exported"
    assert callable(fn)


def test_annotation_card_staged_import():
    """The exact import that broke production must succeed."""
    from src.services.expert_annotation_service import load_subcategories_for_categories  # noqa: F401
