#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator import ContextValidator

class DummyValidator(ContextValidator):
    def __init__(self):
        super().__init__(ai_caller=lambda p: '{"decision": "REJECTED", "reason": "test"}')

v = DummyValidator()
cand = {
    "detail_id": 33800,
    "procurement_id": 163623,
    "category_code": "lighting",
    "subcategory_code": "road_street",
    "matched_term": "светильник",
    "matched_line": "Светильник уличный",
}
results = v.validate_candidates([cand])
print("Validated candidate result keys:", list(results[0].keys()))
print("validator_name:", results[0].get("validator_name"))
print("validator_version:", results[0].get("validator_version"))
print("validation_method:", results[0].get("validation_method"))
