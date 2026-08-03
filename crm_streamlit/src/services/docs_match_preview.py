"""Preview of confirmed document matches for procurement list cards."""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from modules.crm.analytics.tender_row_utils import query_dicts
from src.constants.product_groups import (
    PRODUCT_GROUP_KEYWORDS,
    detect_product_groups_from_text,
    product_group_labels,
)
from src.services.object_models import ObjectViewItem

_VOLUME_RE = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>м²|м2|кв\.?\s*м|м\.?\s*п\.?|мп|п\.?\s*м|шт\.?|комплект(?:ов)?|тн?|кг)",
    re.IGNORECASE,
)

_NO_VOLUME = "объём не извлечён"


def product_name_matches_group(name: str, group_code: str) -> bool:
    if not name or not group_code or group_code == "all":
        return True
    return group_code in detect_product_groups_from_names([name])


def products_for_group(item: ObjectViewItem, group_code: str) -> List[str]:
    if not group_code or group_code == "all":
        return list(item.matched_product_preview or [])
    by_group = item.matched_products_by_group or {}
    if group_code in by_group and by_group[group_code]:
        return list(by_group[group_code])
    return [
        name
        for name in (item.matched_product_preview or [])
        if product_name_matches_group(name, group_code)
    ]


def preview_line_for_group(item: ObjectViewItem, group_code: Optional[str] = None) -> str:
    if not group_code or group_code == "all":
        return item.docs_preview_line or format_docs_preview_line(
            products=item.matched_product_preview or [],
            doc_matches=int(item.doc_matches or 0),
            volume_preview=item.docs_volume_preview or _NO_VOLUME,
        )
    products = products_for_group(item, group_code)
    return format_docs_preview_line(
        products=products,
        doc_matches=len(products),
        volume_preview=item.docs_volume_preview or _NO_VOLUME,
    )


def other_product_groups(item: ObjectViewItem, active_group: Optional[str]) -> List[tuple[str, str]]:
    """Return (code, label) pairs for cross-links excluding active group."""
    from src.constants.product_groups import PRODUCT_GROUP_OPTIONS

    labels = dict(PRODUCT_GROUP_OPTIONS)
    groups = confirmed_product_groups(item)
    if active_group and active_group != "all":
        groups = {g for g in groups if g != active_group}
    return [(code, labels.get(code, code)) for code in labels if code in groups]


def detect_product_groups_from_names(names: Iterable[str]) -> Set[str]:
    """Map confirmed product names to product-group codes."""
    found: Set[str] = set()
    for raw in names:
        text = str(raw or "").lower()
        if not text:
            continue
        for code, keywords in PRODUCT_GROUP_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                found.add(code)
    return found


def extract_volume_preview(texts: Sequence[str], *, max_parts: int = 2) -> str:
    """Pull short quantity snippets from match detail text; else fixed fallback."""
    seen: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in _VOLUME_RE.finditer(str(text)):
            num = match.group("num").replace(",", ".")
            unit = re.sub(r"\s+", "", match.group("unit").lower())
            unit = (
                unit.replace("м2", "м²")
                .replace("кв.м", "м²")
                .replace("квм", "м²")
                .replace("м.п.", "м.п.")
                .replace("мп", "м.п.")
                .replace("п.м", "м.п.")
            )
            snippet = f"~{num} {unit}"
            if snippet not in seen:
                seen.append(snippet)
            if len(seen) >= max_parts:
                return ", ".join(seen)
    return _NO_VOLUME if not seen else ", ".join(seen)


def format_docs_preview_line(
    *,
    products: Sequence[str],
    doc_matches: int,
    volume_preview: str,
) -> str:
    product_part = ", ".join(products) if products else "совпадения без названий"
    vol = (volume_preview or "").strip() or _NO_VOLUME
    return f"В документах: {product_part} · {int(doc_matches or 0)} совп. · {vol}"


def _load_detail_rows(tender_db, keys: Sequence[Tuple[int, str]]) -> List[dict]:
    if not tender_db or not keys:
        return []
    by_table: Dict[str, List[int]] = {}
    for tender_id, registry_type in keys:
        by_table.setdefault(registry_type, []).append(int(tender_id))

    rows: List[dict] = []
    for registry_type, ids in by_table.items():
        uniq = sorted(set(ids))
        placeholders = ",".join(["%s"] * len(uniq))
        chunk = query_dicts(
            tender_db,
            f"""
            SELECT m.tender_id, m.registry_type,
                   d.product_name,
                   COALESCE(d.matched_display_text, '') AS detail_text
            FROM tender_document_matches m
            JOIN tender_document_match_details d ON d.match_id = m.id
            WHERE m.is_interesting = TRUE
              AND m.registry_type = %s
              AND m.tender_id IN ({placeholders})
            """,
            (registry_type, *uniq),
        )
        rows.extend(chunk)
    return rows


def load_match_previews(
    tender_db,
    keys: Sequence[Tuple[int, str]],
) -> Dict[Tuple[int, str], dict]:
    """Aggregate top products + volume preview per tender key."""
    rows = _load_detail_rows(tender_db, keys)
    products: Dict[Tuple[int, str], Counter] = {}
    texts: Dict[Tuple[int, str], List[str]] = {}
    for row in rows:
        tid = row.get("tender_id")
        rt = row.get("registry_type")
        if tid is None or not rt:
            continue
        key = (int(tid), str(rt))
        name = (row.get("product_name") or "").strip()
        if name:
            products.setdefault(key, Counter())[name] += 1
        text = (row.get("detail_text") or "").strip()
        if text:
            texts.setdefault(key, []).append(text)
            if name:
                texts[key].append(name)

    out: Dict[Tuple[int, str], dict] = {}
    all_keys = set(products) | set(texts) | set(keys)
    for key in all_keys:
        counter = products.get(key, Counter())
        top = [name for name, _ in counter.most_common(3)]
        all_names = [name for name, _ in counter.most_common(20)]
        raw_texts = texts.get(key, [])
        vol = extract_volume_preview(raw_texts)
        evidence: List[str] = []
        seen_ev: Set[str] = set()
        for raw in raw_texts:
            compact = " ".join(str(raw or "").split())
            if not compact or compact.lower() in {n.lower() for n in all_names}:
                continue
            if len(compact) > 350:
                compact = compact[:349] + "…"
            low = compact.lower()
            if low in seen_ev:
                continue
            seen_ev.add(low)
            evidence.append(compact)
            if len(evidence) >= 6:
                break
        by_group: Dict[str, List[str]] = {}
        for name, _cnt in counter.most_common():
            for group_code in detect_product_groups_from_names([name]):
                bucket = by_group.setdefault(group_code, [])
                if name not in bucket:
                    bucket.append(name)
                if len(bucket) >= 5:
                    continue
        groups = set(by_group) or detect_product_groups_from_names(top)
        out[key] = {
            "matched_product_preview": top,
            "matched_products_ai": all_names,
            "docs_volume_preview": vol,
            "docs_evidence_preview": evidence,
            "matched_product_groups": groups,
            "matched_products_by_group": by_group,
            "docs_preview_line": format_docs_preview_line(
                products=top,
                doc_matches=sum(counter.values()) or 0,
                volume_preview=vol,
            ),
        }
    return out


def apply_match_previews(tender_db, items: List[ObjectViewItem]) -> None:
    """Fill preview fields on tender items that already have doc hits."""
    keys: List[Tuple[int, str]] = []
    for item in items:
        if not item.tender_id or not item.registry_type:
            continue
        if int(item.doc_matches or 0) <= 0 and int(item.matched_files or 0) <= 0:
            continue
        keys.append((int(item.tender_id), str(item.registry_type)))
    if not keys:
        return

    previews = load_match_previews(tender_db, keys)
    for item in items:
        if not item.tender_id or not item.registry_type:
            continue
        preview = previews.get((int(item.tender_id), str(item.registry_type)))
        if not preview:
            if int(item.doc_matches or 0) > 0:
                item.matched_product_preview = []
                item.matched_products_ai = []
                item.matched_product_groups = set()
                item.docs_volume_preview = _NO_VOLUME
                item.docs_evidence_preview = []
                item.docs_preview_line = format_docs_preview_line(
                    products=[],
                    doc_matches=int(item.doc_matches or 0),
                    volume_preview=_NO_VOLUME,
                )
            continue
        item.matched_product_preview = list(preview["matched_product_preview"])
        item.matched_products_ai = list(preview.get("matched_products_ai") or preview["matched_product_preview"])
        item.matched_product_groups = set(preview["matched_product_groups"])
        item.matched_products_by_group = dict(preview.get("matched_products_by_group") or {})
        item.docs_volume_preview = preview["docs_volume_preview"]
        item.docs_evidence_preview = list(preview.get("docs_evidence_preview") or [])
        # Prefer live doc_matches on the item for the count display.
        item.docs_preview_line = format_docs_preview_line(
            products=item.matched_product_preview,
            doc_matches=int(item.doc_matches or 0),
            volume_preview=item.docs_volume_preview,
        )


def confirmed_product_groups(item: ObjectViewItem) -> Set[str]:
    """Product groups for procurement tabs.

    Priority:
    1) confirmed from parsed docs,
    2) fast title/search fallback for open objects without parsed docs yet.
    """
    if item.matched_product_groups:
        return set(item.matched_product_groups)
    if item.matched_product_preview:
        return detect_product_groups_from_names(item.matched_product_preview)
    text = " ".join(
        str(x or "")
        for x in (
            item.name,
            item.search_text,
            item.ai_subcategory,
            item.ai_primary_class,
            item.ai_object_subtype,
        )
    )
    return detect_product_groups_from_text(text)


def confirmed_product_labels(item: ObjectViewItem) -> List[str]:
    return product_group_labels(confirmed_product_groups(item))
