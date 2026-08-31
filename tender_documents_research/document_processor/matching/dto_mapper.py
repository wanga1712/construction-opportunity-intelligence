from typing import Any, Dict, Optional
from document_processor.dto import MatchDetailResult


def _first_code(value: Any, default: str = "UNKNOWN") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            code = _first_code(item, "")
            if code:
                return code
    return default


def to_match_detail(
    item: Dict[str, Any],
    keyword_meta: Optional[Dict[str, Dict[str, Any]]] = None,
) -> MatchDetailResult:
    row_data = item.get("row_data") or {}
    if not row_data:
        # Fallback to matched_line if no structured row_data
        row_data = {"line": item.get("matched_line", "")}

    keyword = str(item.get("keyword", ""))
    meta = (keyword_meta or {}).get(keyword.lower()) or (keyword_meta or {}).get(keyword) or {}
    category_code = _first_code(
        item.get("category_code")
        or item.get("product_group")
        or meta.get("category_code")
        or meta.get("category_codes")
    )
    subcategory_code = _first_code(
        item.get("subcategory_code")
        or meta.get("subcategory_code")
        or meta.get("subcategory_codes"),
        default="UNKNOWN",
    )

    return MatchDetailResult(
        category_code=category_code,
        subcategory_code=subcategory_code,
        matched_term=keyword,
        term_type=str(item.get("term_type", item.get("match_rule", "KEYWORD"))),
        score=item.get("score", 0.0),
        row_data=row_data,
        page_or_sheet=str(item.get("page_number", item.get("sheet_name", "1"))),
        row_number=item.get("line_number", -1),
        context_before=item.get("context_before", {}),
        context_after=item.get("context_after", {}),
        match_method=str(item.get("match_method", "UNKNOWN") or "UNKNOWN"),
        validation_status=str(item.get("validation_status", "UNKNOWN") or "UNKNOWN"),
        validation_method=item.get("validation_method"),
        validation_reason=item.get("validation_reason"),
        validated_at=item.get("validated_at"),
        validator_name=item.get("validator_name"),
        validator_version=item.get("validator_version"),
    )

