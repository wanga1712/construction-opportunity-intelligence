#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator import ContextValidator, VALIDATOR_VERSION, VALIDATION_METHOD

v = ContextValidator(ai_caller=lambda p: '{"decision": "REJECTED", "reason": "test"}')
c = {
    "detail_id": 1,
    "category_code": "lighting",
    "subcategory_code": "road_street",
    "matched_term": "светильник",
    "matched_line": "Светильник уличный",
}
res = v.validate_single(c)
print("validate_single result:", res)
print("VALIDATOR_VERSION:", VALIDATOR_VERSION)
print("VALIDATION_METHOD:", VALIDATION_METHOD)
