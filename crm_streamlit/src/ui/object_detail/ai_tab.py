"""Public assembly point for object-detail AI controls."""
from __future__ import annotations

from .ai_chat import (
    _render_category_label,
    _render_document_upload,
    _render_procurement_chat,
)
from .ai_shadow import _render_ai_shadow, _render_ai_shadow_v2


def _can_dismiss(item) -> bool:
    return bool(
        item.tender_id
        and item.registry_type
        and "nashdom" not in (item.sources or [])
    )


__all__ = [
    "_can_dismiss",
    "_render_ai_shadow",
    "_render_ai_shadow_v2",
    "_render_procurement_chat",
    "_render_category_label",
    "_render_document_upload",
]
