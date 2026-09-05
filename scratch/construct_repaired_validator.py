#!/usr/bin/env python3
"""
Constructs repaired context_validator.py starting from parent c7e28ee baseline.
Adds ONLY context hydration functionality and no semantic decision policy changes.
"""
import subprocess
import os

# 1. Fetch exact file from parent commit c7e28ee
res = subprocess.run(
    ["git", "show", "c7e28ee55316b227398865f2eb0ba8452d2d73da:tender_documents_research/document_processor/context_validator.py"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    check=True,
)
base_content = res.stdout

# Check that base_content has exact c7e28ee SHA
import hashlib
print("Base content SHA256:", hashlib.sha256(base_content.encode("utf-8")).hexdigest())

# Hydration helper code to insert before _normalize_whitespace or after it
hydration_helpers = '''

def _is_empty_context(val) -> bool:
    """Treats None, empty string, whitespace-only, {}, [], '{}', '[]', 'null' as empty."""
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


def _candidate_matched_line(candidate: Dict[str, Any]) -> str:
    """Extracts the best matched text from candidate using hydration precedence."""
    matched_line = candidate.get("matched_line") or ""
    if isinstance(matched_line, str):
        matched_line = matched_line.strip()
    if matched_line:
        return matched_line
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
    return str(matched_line)
'''

# Find insertion point after _normalize_whitespace
norm_ws_marker = "def _normalize_whitespace(text: str) -> str:"
norm_ws_pos = base_content.find(norm_ws_marker)
# find end of _normalize_whitespace function
end_norm_ws = base_content.find("\n\nclass ContextValidator:", norm_ws_pos)

patched = base_content[:end_norm_ws] + hydration_helpers + base_content[end_norm_ws:]

# Now in ContextValidator.build_context_block:
# Insert candidate = hydrate_candidate_context(candidate) at the start of build_context_block
old_build_start = '    def build_context_block(self, candidate: Dict[str, Any]) -> str:\n        """Constructs a bounded, informative context block for Qwen."""\n        pid = candidate.get("procurement_id", "")'

new_build_start = '    def build_context_block(self, candidate: Dict[str, Any]) -> str:\n        """Constructs a bounded, informative context block for Qwen."""\n        candidate = hydrate_candidate_context(candidate)\n        pid = candidate.get("procurement_id", "")'

assert old_build_start in patched, "build_context_block start not found"
patched = patched.replace(old_build_start, new_build_start, 1)

# In build_context_block, replace matched_line extraction with _candidate_matched_line(candidate)
old_matched_line_block = '''        matched_line = candidate.get("matched_line") or ""
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

new_matched_line_block = '        matched_line = _candidate_matched_line(candidate)'

assert old_matched_line_block in patched, "matched_line block not found"
patched = patched.replace(old_matched_line_block, new_matched_line_block, 1)

target_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator.py",
)

with open(target_path, "w", encoding="utf-8") as f:
    f.write(patched)

print("Successfully wrote repaired context_validator.py")
