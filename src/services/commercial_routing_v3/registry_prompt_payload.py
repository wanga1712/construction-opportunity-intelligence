"""Phase 9 — data-driven ACTIVE registry payload for SHADOW prompts.

Does not mutate production taxonomy. Optional in-memory extensions (e.g. paint)
are SHADOW-only and never written to crm_product_categories.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROMPT_REGISTRY_PAYLOAD_VERSION = "V9_FULL_ACTIVE_REGISTRY_1"

# Subcategories deferred: first-pass routing selects category_code only.
SUBCATEGORY_ARCHITECTURE = "DEFERRED_AFTER_CATEGORY_SELECTION"


def _as_list(val: Any) -> List[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _trim(text: Any, limit: int = 240) -> Optional[str]:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    return s if len(s) <= limit else (s[: limit - 1] + "…")


def build_active_registry_payload(
    registry_rows: Sequence[Dict[str, Any]],
    *,
    extra_shadow_categories: Optional[Sequence[Dict[str, Any]]] = None,
    include_subcategories: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Compact ACTIVE registry rows for the model.

    Every category in ``registry_rows`` is included (no title/OKPD filter).
    ``extra_shadow_categories`` are SHADOW-only injections (not persisted).
    """
    by_code: Dict[str, Dict[str, Any]] = {}
    for row in registry_rows:
        code = str(row.get("category_code") or "").strip()
        if not code:
            continue
        item: Dict[str, Any] = {
            "category_code": code,
            "category_name": str(row.get("category_name") or code),
        }
        desc = _trim(row.get("description"))
        if desc:
            item["description"] = desc
        aliases = [str(a) for a in _as_list(row.get("aliases")) if str(a).strip()][:12]
        if aliases:
            item["aliases"] = aliases
        pos = [str(a) for a in _as_list(row.get("positive_signals")) if str(a).strip()][:8]
        if pos:
            item["positive_scope"] = pos
        neg = [str(a) for a in _as_list(row.get("negative_contexts")) if str(a).strip()][:8]
        if neg:
            item["negative_scope"] = neg
        life = row.get("lifecycle_state")
        if life:
            item["lifecycle_state"] = str(life)
        if include_subcategories:
            subs = row.get("subcategories") or []
            clean_subs = []
            for s in subs:
                if isinstance(s, dict) and s.get("subcategory_code"):
                    clean_subs.append({"subcategory_code": str(s["subcategory_code"])})
                elif s:
                    clean_subs.append({"subcategory_code": str(s)})
            if clean_subs:
                item["subcategories"] = clean_subs[:20]
        by_code[code] = item

    for row in extra_shadow_categories or []:
        code = str(row.get("category_code") or "").strip()
        if not code:
            continue
        by_code[code] = {
            "category_code": code,
            "category_name": str(row.get("category_name") or code),
            "description": _trim(row.get("description")) or str(row.get("category_name") or code),
            "aliases": [str(a) for a in _as_list(row.get("aliases")) if str(a).strip()][:12],
            "lifecycle_state": "ACTIVE",
            "shadow_extension": True,
        }

    ordered = [by_code[k] for k in sorted(by_code.keys())]
    codes = [str(x["category_code"]) for x in ordered]
    return ordered, codes


def registry_payload_json(
    payload: Sequence[Dict[str, Any]],
    *,
    ensure_ascii: bool = False,
) -> str:
    return json.dumps(list(payload), ensure_ascii=ensure_ascii, default=str)


def estimate_prompt_chars(
    *,
    base_prompt_chars: int,
    payload: Sequence[Dict[str, Any]],
    scale: int = 1,
) -> Dict[str, int]:
    """Rough char/token estimates for registry scale stress (no retrieval)."""
    one = registry_payload_json(payload)
    # Approximate: duplicate payload scale times (synthetic growth).
    scaled_payload_chars = len(one) * max(1, scale)
    total = base_prompt_chars - len(one) + scaled_payload_chars
    # ~4 chars/token heuristic for mixed RU/EN JSON prompts
    tokens = max(1, total // 4)
    return {
        "scale": scale,
        "prompt_chars_est": total,
        "prompt_tokens_est": tokens,
        "registry_payload_chars": scaled_payload_chars,
    }


PAINT_SHADOW_CATEGORY: Dict[str, Any] = {
    "category_code": "paint",
    "category_name": "Краски и лакокрасочные материалы",
    "description": (
        "Лакокрасочные материалы: краски, эмали, грунтовки, лаки для фасадов, "
        "внутренних работ и металлоконструкций"
    ),
    "aliases": ["краска", "краски", "лакокрасочные", "эмаль", "грунтовка", "ЛКМ"],
}
