"""Phase 10 — data-driven category_ref transport (SHADOW).

Refs are generated from ACTIVE registry snapshot order. Resolution is
dereference only — not semantic taxonomy inference.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.commercial_routing_v3.registry_prompt_payload import (
    build_active_registry_payload,
)


def assign_category_refs(
    registry_rows: Sequence[Dict[str, Any]],
    *,
    extra_shadow_categories: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str], Dict[str, str]]:
    """Return (payload_with_ref, ref_to_code, code_to_ref).

    Refs are C01..Cn in sorted category_code order (deterministic).
    """
    payload, codes = build_active_registry_payload(
        registry_rows,
        extra_shadow_categories=extra_shadow_categories,
        include_subcategories=False,
    )
    ref_to_code: Dict[str, str] = {}
    code_to_ref: Dict[str, str] = {}
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(payload, start=1):
        ref = f"C{i:02d}"
        code = str(item["category_code"])
        row = dict(item)
        row["ref"] = ref
        out.append(row)
        ref_to_code[ref] = code
        code_to_ref[code] = ref
    return out, ref_to_code, code_to_ref


def resolve_category_ref(
    ref: Any,
    *,
    ref_to_code: Dict[str, str],
) -> Optional[str]:
    """Exact ref → category_code. No fuzzy / nearest-neighbor repair."""
    if ref is None:
        return None
    key = str(ref).strip().upper()
    if not key:
        return None
    # Canonicalize C1 → C01 if present; still exact lookup only after normalize
    if key.startswith("C") and key[1:].isdigit():
        key = f"C{int(key[1:]):02d}"
    return ref_to_code.get(key)
