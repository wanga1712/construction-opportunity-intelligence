"""Build category-first factual summaries for procurement card rendering."""
from __future__ import annotations

from typing import Any, Dict, Iterable


def _row_key(product: Dict[str, Any]) -> tuple:
    return (
        str(product.get("category_code") or ""),
        str(product.get("subcategory_code") or ""),
        str(product.get("row_or_line") or ""),
        str(product.get("source_quote") or ""),
        str(product.get("material") or product.get("product_name_raw") or "").strip().casefold(),
        str(product.get("quantity")),
        str(product.get("unit") or "").strip().upper(),
        str(product.get("unit_price")),
        str(product.get("total")),
    )


def summarize_category_cards(cards: Iterable[Dict[str, Any]]) -> list[dict[str, Any]]:
    """Return category totals followed by unique factual subcategory totals."""
    grouped: dict[str, dict[str, Any]] = {}
    for card in cards or []:
        category = str(card.get("category_code") or "").strip()
        if not category:
            continue
        key = category
        summary = grouped.setdefault(key, {
            "category_code": category,
            "category_name": card.get("category_name") or category,
            "tracks": set(),
            "rows": {},
            "evidence": {},
            "subcategories": {},
        })
        track = str(card.get("track") or "").strip()
        if track:
            summary["tracks"].add(track)
        subcategory = str(card.get("subcategory_code") or "").strip()
        products = list(card.get("products") or [])
        for product in products:
            row_key = _row_key(product)
            summary["rows"].setdefault(row_key, product)
            if subcategory:
                sub = summary["subcategories"].setdefault(
                    subcategory,
                    {
                        "rows": {},
                        "evidence": {},
                        "subcategory_name": card.get("subcategory_name") or subcategory,
                    },
                )
                sub["rows"].setdefault(row_key, product)
        for evidence_row in card.get("evidence_materials") or []:
            row_key = _row_key(evidence_row)
            summary["evidence"].setdefault(row_key, evidence_row)
            if subcategory:
                sub = summary["subcategories"].setdefault(
                    subcategory,
                    {
                        "rows": {},
                        "evidence": {},
                        "subcategory_name": card.get("subcategory_name") or subcategory,
                    },
                )
                sub["evidence"].setdefault(row_key, evidence_row)

    result = []
    for summary in grouped.values():
        rows = list(summary.pop("rows").values())
        summary["track"] = " / ".join(sorted(summary.pop("tracks"))) or None
        value = [float(row["total"]) for row in rows if row.get("total") is not None]
        summary["line_count"] = len(rows)
        summary["evidence_line_count"] = len(summary.pop("evidence"))
        summary["product_count"] = len({
            str(row.get("material") or row.get("product_name_raw") or "").strip().casefold()
            for row in rows
        } - {""})
        summary["material_value"] = round(sum(value), 2) if value else None
        summary["duplicate_source_copies_collapsed"] = sum(
            max(0, int(row.get("duplicate_source_count") or 1) - 1)
            for row in rows
        )
        subs = []
        for code, item in sorted(summary["subcategories"].items()):
            sub_rows = list(item["rows"].values())
            evidence_rows = item.get("evidence") or {}
            sub_totals = [
                float(row["total"]) for row in sub_rows
                if row.get("total") is not None
            ]
            subs.append({
                "subcategory_code": code,
                "subcategory_name": item.get("subcategory_name") or code,
                "line_count": len(sub_rows),
                "evidence_line_count": len(evidence_rows),
                "product_count": len({
                    str(row.get("material") or row.get("product_name_raw") or "").strip().casefold()
                    for row in sub_rows
                } - {""}),
                "material_value": round(sum(sub_totals), 2) if sub_totals else None,
            })
        summary["subcategories"] = subs
        result.append(summary)
    return sorted(result, key=lambda row: (str(row["category_name"]), row["category_code"]))
