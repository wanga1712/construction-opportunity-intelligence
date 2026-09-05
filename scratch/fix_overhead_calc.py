#!/usr/bin/env python3
"""
Fixes overhead budget calculation in _build_visible_document_context_pair.
Reserves full marker overhead (170 chars) so doc_section_str is guaranteed <= max_doc_budget.
"""
import os

VAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator.py",
)

with open(VAL_PATH, "r", encoding="utf-8") as f:
    val_src = f.read()

old_overhead = "doc_header_overhead = len(\"[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n\")"
new_overhead = "doc_header_overhead = len(\"[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n\") + len(prefix_marker) + len(suffix_marker) + len(mline_marker) + 10"

assert old_overhead in val_src, "Could not find doc_header_overhead line in context_validator.py"

val_src = val_src.replace(old_overhead, new_overhead, 1)

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Successfully updated overhead calculation in context_validator.py")
