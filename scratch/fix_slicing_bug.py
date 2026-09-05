#!/usr/bin/env python3
"""
Fixes negative index slicing bug in _build_visible_document_context_pair.
In Python: string[-0:] returns string (the full string)!
Must use string[-n:] if n > 0 else "".
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

# Fix line 258 where before_text[-avail_before_net:] evaluated before_text[-0:] -> full string!
old_slice = "used_before = before_text[-avail_before_net:]"
new_slice = "used_before = before_text[-avail_before_net:] if avail_before_net > 0 else \"\""

assert old_slice in val_src, "Could not find slice line in context_validator.py"
val_src = val_src.replace(old_slice, new_slice, 1)

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Successfully fixed slicing bug in context_validator.py")
