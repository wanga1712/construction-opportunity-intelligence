#!/usr/bin/env python3
"""
Applies R3-4F-B Document Context Trust Boundary Repair.
Modifies context_validator.py and context_validator_service.py.
"""
import os

VAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator.py",
)

SERVICE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator_service.py",
)

# 1. Read context_validator.py
with open(VAL_PATH, "r", encoding="utf-8") as f:
    val_src = f.read()

# Update version constants
val_src = val_src.replace('VALIDATOR_VERSION = "v2"', 'VALIDATOR_VERSION = "v3"')
val_src = val_src.replace('VALIDATION_METHOD = "QWEN_CONTEXT_V2"', 'VALIDATION_METHOD = "QWEN_CONTEXT_V3"')
val_src = val_src.replace('PROMPT_VERSION = "context_validator_v2"', 'PROMPT_VERSION = "context_validator_v3"')

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Updated versioning in context_validator.py to v3/QWEN_CONTEXT_V3")
