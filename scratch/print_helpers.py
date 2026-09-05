#!/usr/bin/env python3
import inspect
from tender_documents_research.document_processor.context_validator import (
    _candidate_matched_line,
    _is_structurally_ambiguous,
    _normalize_whitespace,
)

print("=== _candidate_matched_line ===")
print(inspect.getsource(_candidate_matched_line))
print("=== _is_structurally_ambiguous ===")
print(inspect.getsource(_is_structurally_ambiguous))
print("=== _normalize_whitespace ===")
print(inspect.getsource(_normalize_whitespace))
