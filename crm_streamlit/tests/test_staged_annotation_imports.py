"""Regression: staged annotation decision path must not import nonexistent symbols.

Ticket: CRM-V3-STAGED-CARD-RUNTIME-BREAKAGE-FIX-1

This test exercises the *import-time* path that
``_render_primary_scope_decision`` in ``annotation_card.py`` triggers
when the user selects decision == YES.  That code lazily imports
``load_subcategories_for_categories`` from ``expert_annotation_service``.
A prior bug (c76bdff) imported the nonexistent symbol
``load_subcategories_by_category`` which crashed the real UI.
"""
from __future__ import annotations

import importlib


def test_primary_scope_decision_imports_resolve():
    """Importing annotation_card must NOT raise ImportError for any symbol."""
    # Force a clean import to catch any stale cached state.
    mod = importlib.import_module(
        "src.ui.components.analytics_v2.annotation_card"
    )
    assert hasattr(mod, "_render_primary_scope_decision")
    assert hasattr(mod, "render_annotation_section")


def test_staged_subcategory_api_exists_in_service():
    """The canonical batch subcategory API must exist in expert_annotation_service."""
    from src.services.expert_annotation_service import (
        load_subcategories_for_categories,  # noqa: F401
    )
    assert callable(load_subcategories_for_categories)


def test_nonexistent_load_subcategories_by_category_absent():
    """Ensure the broken symbol is NOT present in expert_annotation_service."""
    from src.services import expert_annotation_service

    assert not hasattr(expert_annotation_service, "load_subcategories_by_category"), (
        "load_subcategories_by_category should NOT exist — "
        "use load_subcategories_for_categories"
    )


def test_staged_annotation_ui_controls_importable():
    """The staged annotation widgets used by _render_primary_scope_decision must import."""
    from src.ui.components.analytics_v2.staged_annotation_ui import (
        render_product_category_controls,  # noqa: F401
        render_object_stage_controls,  # noqa: F401
        render_procurement_mode_controls,  # noqa: F401
        render_commercial_and_medal_controls,  # noqa: F401
        read_staged_draft,  # noqa: F401
        validate_staged_minimum,  # noqa: F401
        init_staged_draft_from_payload,  # noqa: F401
        render_source_contour_banner,  # noqa: F401
    )


def test_annotation_category_gate_importable():
    """The category gate symbols used by _render_primary_scope_decision must import."""
    from src.services.annotation_category_gate import (
        IN_CATEGORY,  # noqa: F401
        OUT_OF_CATEGORY,  # noqa: F401
        UNCERTAIN,  # noqa: F401
        build_in_category_payload,  # noqa: F401
        build_out_of_category_payload,  # noqa: F401
    )
