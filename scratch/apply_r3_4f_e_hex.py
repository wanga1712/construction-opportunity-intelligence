import os
import bytes

# This script applies R3-4F-E changes using raw UTF-8 hex decoding
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VAL_PATH = os.path.join(REPO_ROOT, "tender_documents_research", "document_processor", "context_validator.py")
SVC_PATH = os.path.join(REPO_ROOT, "tender_documents_research", "document_processor", "context_validator_service.py")
V2_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_semantics_v2.py")
V3_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_v3_trust_boundary.py")
V4_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_v4_decision_boundary.py")

os.system(f"git checkout -- {VAL_PATH} {SVC_PATH} {V2_TEST_PATH} {V3_TEST_PATH}")
