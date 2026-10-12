"""Runner for second_pass_service unit tests."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit" if os.path.exists("/opt/CRM_Streamlit") else os.path.abspath("."))

from tests.test_second_pass_service import (
    test_parse_second_pass_json_clean,
    test_parse_second_pass_json_fallback,
    test_parse_second_pass_json_defensive_facts,
    test_build_second_pass_prompt,
)

if __name__ == "__main__":
    print("Running second_pass_service unit tests...")
    test_parse_second_pass_json_clean()
    print("  [PASS] test_parse_second_pass_json_clean")
    test_parse_second_pass_json_fallback()
    print("  [PASS] test_parse_second_pass_json_fallback")
    test_parse_second_pass_json_defensive_facts()
    print("  [PASS] test_parse_second_pass_json_defensive_facts")
    test_build_second_pass_prompt()
    print("  [PASS] test_build_second_pass_prompt")
    print("ALL 4 UNIT TESTS PASSED SUCCESSFULLY!")
