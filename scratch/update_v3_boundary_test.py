#!/usr/bin/env python3
"""
Updates test_v3_versioning_constants in test_context_validator_v3_trust_boundary.py to check for v4.
"""
import os

TEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "test_context_validator_v3_trust_boundary.py",
)

with open(TEST_PATH, "r", encoding="utf-8") as f:
    src = f.read()

src = src.replace('assert VALIDATOR_VERSION == "v3"', 'assert VALIDATOR_VERSION == "v4"')
src = src.replace('assert VALIDATION_METHOD == "QWEN_CONTEXT_V3"', 'assert VALIDATION_METHOD == "QWEN_CONTEXT_V4"')
src = src.replace('assert PROMPT_VERSION == "context_validator_v3"', 'assert PROMPT_VERSION == "context_validator_v4"')

with open(TEST_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Successfully updated test_context_validator_v3_trust_boundary.py")
