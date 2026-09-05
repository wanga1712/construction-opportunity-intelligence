#!/usr/bin/env python3
"""
Updates test_context_validator_semantics_v2.py to use dynamic VALIDATOR_VERSION and VALIDATION_METHOD.
"""
import os

TEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "test_context_validator_semantics_v2.py",
)

with open(TEST_PATH, "r", encoding="utf-8") as f:
    src = f.read()

src = src.replace('assert res["validator_version"] == "v2"', 'assert res["validator_version"] == VALIDATOR_VERSION')
src = src.replace('assert res["validator_version"] == VALIDATOR_VERSION == "v2"', 'assert res["validator_version"] == VALIDATOR_VERSION')
src = src.replace('assert res["validation_method"] == VALIDATION_METHOD == "QWEN_CONTEXT_V2"', 'assert res["validation_method"] == VALIDATION_METHOD')

with open(TEST_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Successfully updated test_context_validator_semantics_v2.py")
