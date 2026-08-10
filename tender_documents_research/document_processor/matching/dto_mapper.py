from typing import Any, Dict
from document_processor.dto import MatchDetailResult

def to_match_detail(item: Dict[str, Any]) -> MatchDetailResult:
    row_data = item.get("row_data") or {}
    if not row_data:
        # Fallback to matched_line if no structured row_data
        row_data = {"line": item.get("matched_line", "")}

    return MatchDetailResult(
        category_code="UNKNOWN", # Should be assigned later/mapped
        subcategory_code="UNKNOWN",
        matched_term=item.get("keyword", ""),
        term_type="KEYWORD",
        score=item.get("score", 0.0),
        row_data=row_data,
        page_or_sheet=str(item.get("page_number", item.get("sheet_name", "1"))),
        row_number=item.get("line_number", -1),
        context_before=item.get("context_before", {}),
        context_after=item.get("context_after", {})
    )
