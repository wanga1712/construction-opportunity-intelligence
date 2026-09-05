#!/usr/bin/env python3
"""
Applies R3-4D-A validation attempt terminality fix to context_validator_service.py.
"""
import os

SERVICE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator_service.py",
)

with open(SERVICE_PATH, "r", encoding="utf-8") as f:
    src = f.read()

old_query_where = '''            WHERE (
                d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING')
                OR d.validation_status IS NULL
            )
            AND d.pipeline_generation = %s'''

new_query_where = '''            WHERE (
                d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING')
                OR d.validation_status IS NULL
            )
            AND d.validated_at IS NULL
            AND d.pipeline_generation = %s'''

assert old_query_where in src, "old_query_where not found in context_validator_service.py"
src = src.replace(old_query_where, new_query_where, 1)

with open(SERVICE_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Applied R3-4D-A terminality fix to context_validator_service.py")
