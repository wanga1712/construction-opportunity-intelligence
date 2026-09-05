#!/usr/bin/env python3
"""
Apply the hydrate_candidate_context fix to context_validator.py.
Reads the existing file, applies targeted patches, writes back.
NO SYSTEM_PROMPT changes. NO threshold changes.
"""
import re

VALIDATOR_PATH = "/opt/CRM_Streamlit/tender_documents_research/document_processor/context_validator.py"

with open(VALIDATOR_PATH, "r", encoding="utf-8") as f:
    src = f.read()

# ============================================================
# PATCH 1: Add hydrate_candidate_context() and _format_raw_cells()
# after _normalize_whitespace and before _candidate_matched_line
# ============================================================

hydration_code = '''

def _is_empty_context(val) -> bool:
    """Treats None, empty string, whitespace-only, {}, [], '{}', '[]' as empty."""
    if val is None:
        return True
    if isinstance(val, dict) and not val:
        return True
    if isinstance(val, list) and not val:
        return True
    if isinstance(val, str):
        stripped = val.strip()
        if not stripped or stripped in ('{}', '[]', 'null', 'None'):
            return True
    return False


def _safe_parse_json(val):
    """Parse JSON string safely; returns parsed value or original on failure."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def _format_raw_cells(raw_cells: list) -> str:
    """Formats raw_cells list into a human-readable table row string.
    
    Preserves useful factual structure: column text, headers, units, quantities.
    """
    if not raw_cells or not isinstance(raw_cells, list):
        return ""
    parts = []
    for cell in raw_cells:
        if isinstance(cell, dict):
            text = str(cell.get("text", "")).strip()
            if text:
                parts.append(text)
        elif isinstance(cell, str):
            parts.append(cell.strip())
    return " | ".join(parts) if parts else ""


def hydrate_candidate_context(candidate: dict) -> dict:
    """Single authority for resolving matched_line, context_before, context_after.
    
    Precedence for each field:
      A. Explicit non-empty candidate field (from DB column)
      B. Fallback to row_data nested field
      C. For matched_line: also try raw_cells formatting
    
    Returns a NEW dict with resolved 'matched_line', 'context_before', 'context_after'
    keys added/overwritten. Does NOT mutate the original candidate.
    """
    result = dict(candidate)
    
    # Parse row_data if needed
    row_data = candidate.get("row_data")
    if isinstance(row_data, str):
        row_data = _safe_parse_json(row_data)
    if not isinstance(row_data, dict):
        row_data = {}
    
    # --- matched_line ---
    matched_line = candidate.get("matched_line") or ""
    if isinstance(matched_line, str):
        matched_line = matched_line.strip()
    
    if not matched_line:
        # Fallback B: row_data.matched_line / matched_display_text / text
        matched_line = (
            row_data.get("matched_line")
            or row_data.get("matched_display_text")
            or row_data.get("text")
            or ""
        )
        if isinstance(matched_line, str):
            matched_line = matched_line.strip()
    
    if not matched_line:
        # Fallback C: format raw_cells as matched text
        matched_line = _format_raw_cells(row_data.get("raw_cells"))
    
    result["matched_line"] = matched_line
    
    # --- context_before ---
    db_before = candidate.get("context_before")
    if _is_empty_context(db_before):
        # Fallback to row_data.context_before
        rd_before = row_data.get("context_before")
        if isinstance(rd_before, str):
            rd_before = _safe_parse_json(rd_before)
        if isinstance(rd_before, list) and rd_before:
            result["context_before"] = rd_before
        else:
            result["context_before"] = []
    else:
        # Explicit DB value is non-empty - keep it
        if isinstance(db_before, str):
            db_before = _safe_parse_json(db_before)
        result["context_before"] = db_before if isinstance(db_before, list) else [db_before] if db_before else []
    
    # --- context_after ---
    db_after = candidate.get("context_after")
    if _is_empty_context(db_after):
        # Fallback to row_data.context_after
        rd_after = row_data.get("context_after")
        if isinstance(rd_after, str):
            rd_after = _safe_parse_json(rd_after)
        if isinstance(rd_after, list) and rd_after:
            result["context_after"] = rd_after
        else:
            result["context_after"] = []
    else:
        # Explicit DB value is non-empty - keep it
        if isinstance(db_after, str):
            db_after = _safe_parse_json(db_after)
        result["context_after"] = db_after if isinstance(db_after, list) else [db_after] if db_after else []
    
    return result

'''

# Find the insertion point: after _normalize_whitespace, before _candidate_matched_line
# Pattern: end of _normalize_whitespace function, then blank line(s), then def _candidate_matched_line
match = re.search(
    r'(def _normalize_whitespace\(text: str\).*?return re\.sub\(r"\\s\+", " ", text\)\.strip\(\)\.lower\(\)\n)',
    src,
    re.DOTALL,
)
if not match:
    raise RuntimeError("Could not find _normalize_whitespace function")

insert_pos = match.end()
# Skip any blank lines
while insert_pos < len(src) and src[insert_pos] in ('\n', '\r'):
    insert_pos += 1

src = src[:insert_pos] + hydration_code + "\n" + src[insert_pos:]


# ============================================================
# PATCH 2: Update _candidate_matched_line to use hydrated matched_line and raw_cells
# ============================================================

old_candidate_matched_line = '''def _candidate_matched_line(candidate: Dict[str, Any]) -> str:
    matched_line = candidate.get("matched_line") or ""
    row_data = candidate.get("row_data")
    if isinstance(row_data, str):
        try:
            row_data = json.loads(row_data)
        except Exception:
            row_data = {"matched_line": row_data}
    if not matched_line and isinstance(row_data, dict):
        matched_line = (
            row_data.get("matched_line")
            or row_data.get("matched_display_text")
            or row_data.get("text")
            or ""
        )
    return str(matched_line)'''

new_candidate_matched_line = '''def _candidate_matched_line(candidate: Dict[str, Any]) -> str:
    """Extracts the best matched text from candidate using hydration precedence."""
    # Use hydrated matched_line if available (set by hydrate_candidate_context)
    matched_line = candidate.get("matched_line") or ""
    if isinstance(matched_line, str):
        matched_line = matched_line.strip()
    if matched_line:
        return matched_line
    # Fallback: parse row_data directly
    row_data = candidate.get("row_data")
    if isinstance(row_data, str):
        row_data = _safe_parse_json(row_data)
        if not isinstance(row_data, dict):
            row_data = {"matched_line": str(row_data)}
    if isinstance(row_data, dict):
        matched_line = (
            row_data.get("matched_line")
            or row_data.get("matched_display_text")
            or row_data.get("text")
            or ""
        )
        if not matched_line:
            matched_line = _format_raw_cells(row_data.get("raw_cells"))
    return str(matched_line)'''

if old_candidate_matched_line not in src:
    raise RuntimeError("Could not find _candidate_matched_line function to patch")
src = src.replace(old_candidate_matched_line, new_candidate_matched_line)


# ============================================================
# PATCH 3: Update build_context_block to hydrate before building
# ============================================================

# Add hydration call at the start of build_context_block
old_build_start = '''    def build_context_block(self, candidate: Dict[str, Any]) -> str:
        """Constructs a bounded, informative context block for Qwen."""
        pid = candidate.get("procurement_id", "")'''

new_build_start = '''    def build_context_block(self, candidate: Dict[str, Any]) -> str:
        """Constructs a bounded, informative context block for Qwen.
        
        Hydrates context from row_data when DB columns are empty.
        """
        candidate = hydrate_candidate_context(candidate)
        pid = candidate.get("procurement_id", "")'''

if old_build_start not in src:
    raise RuntimeError("Could not find build_context_block start to patch")
src = src.replace(old_build_start, new_build_start)

# Remove the duplicate row_data fallback in build_context_block since hydrate handles it
old_row_data_fallback = '''        matched_line = _candidate_matched_line(candidate)
        row_data = candidate.get("row_data")
        if isinstance(row_data, str):
            try:
                row_data = json.loads(row_data)
            except Exception:
                row_data = {"matched_line": row_data}
        if not matched_line and isinstance(row_data, dict):
            matched_line = (
                row_data.get("matched_line")
                or row_data.get("matched_display_text")
                or row_data.get("text")
                or ""
            )'''

new_row_data_fallback = '''        matched_line = _candidate_matched_line(candidate)'''

if old_row_data_fallback not in src:
    raise RuntimeError("Could not find row_data fallback block in build_context_block")
src = src.replace(old_row_data_fallback, new_row_data_fallback, 1)


# ============================================================
# WRITE
# ============================================================

with open(VALIDATOR_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print(f"PATCHED {VALIDATOR_PATH}")
print(f"NEW FILE LENGTH: {len(src)} chars")

# Verify the patched file imports
import importlib
import sys
# Clear cached modules
for mod_name in list(sys.modules.keys()):
    if 'context_validator' in mod_name:
        del sys.modules[mod_name]

# Quick smoke test
from tender_documents_research.document_processor.context_validator import (
    hydrate_candidate_context,
    _is_empty_context,
    _format_raw_cells,
    _candidate_matched_line,
    ContextValidator,
)

# Test hydration with production-like row_data
test_candidate = {
    "detail_id": 35176,
    "procurement_id": 997,
    "matched_term": "ex-светильники",
    "matched_line": "",  # empty in DB
    "context_before": {},  # empty dict from jsonb
    "context_after": {},  # empty dict from jsonb
    "row_data": {
        "values": {"position": "Светильник с люминесцентными лампами до 4"},
        "headers": {"position": "Переключатель 3-х позиционный, 25А"},
        "raw_cells": [
            {"col": "A", "text": "3", "header": "9"},
            {"col": "B", "text": "Светильник с люминесцентными лампами до 4", "header": "Переключатель 3-х позиционный, 25А"},
            {"col": "C", "text": "шт", "header": "шт"},
            {"col": "D", "text": "49", "header": "2"},
        ],
        "context_before": [
            "2 | Электрический щит | шт | 5",
            "3 | Светильник с лампами накаливания | шт | 36",
        ],
        "context_after": [
            "4 | Счетчик , трехфазный, | шт | 1",
        ],
        "context_lines": 7,
        "header_line_number": 4658,
        "column_map": {"position": 1},
    },
}

hydrated = hydrate_candidate_context(test_candidate)
print(f"\nHYDRATION TEST:")
print(f"  matched_line: '{hydrated['matched_line']}'")
print(f"  context_before: {hydrated['context_before']}")
print(f"  context_after: {hydrated['context_after']}")

assert hydrated["matched_line"], "matched_line should not be empty after hydration"
assert hydrated["context_before"], "context_before should not be empty after hydration"
assert hydrated["context_after"], "context_after should not be empty after hydration"

# Test _is_empty_context
assert _is_empty_context(None) == True
assert _is_empty_context({}) == True
assert _is_empty_context([]) == True
assert _is_empty_context("") == True
assert _is_empty_context("  ") == True
assert _is_empty_context("{}") == True
assert _is_empty_context("[]") == True
assert _is_empty_context("null") == True
assert _is_empty_context(["something"]) == False
assert _is_empty_context({"key": "val"}) == False

# Test explicit context precedence
explicit_candidate = dict(test_candidate)
explicit_candidate["matched_line"] = "EXPLICIT LINE"
explicit_candidate["context_before"] = ["EXPLICIT BEFORE"]
explicit_candidate["context_after"] = ["EXPLICIT AFTER"]
hydrated_explicit = hydrate_candidate_context(explicit_candidate)
assert hydrated_explicit["matched_line"] == "EXPLICIT LINE", "Explicit matched_line must win"
assert hydrated_explicit["context_before"] == ["EXPLICIT BEFORE"], "Explicit context_before must win"
assert hydrated_explicit["context_after"] == ["EXPLICIT AFTER"], "Explicit context_after must win"

print("\nALL HYDRATION SMOKE TESTS PASSED")
print("PATCH APPLIED SUCCESSFULLY")
