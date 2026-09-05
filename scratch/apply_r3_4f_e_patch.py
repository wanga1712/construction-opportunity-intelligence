import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VAL_PATH = os.path.join(REPO_ROOT, "tender_documents_research", "document_processor", "context_validator.py")
SVC_PATH = os.path.join(REPO_ROOT, "tender_documents_research", "document_processor", "context_validator_service.py")
V2_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_semantics_v2.py")
V3_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_v3_trust_boundary.py")
V4_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_v4_decision_boundary.py")

# Reset tracked files from git HEAD
os.system(f"git checkout -- {VAL_PATH} {SVC_PATH} {V2_TEST_PATH} {V3_TEST_PATH}")

with open("scratch/sys_prompt_raw.txt", "rb") as f:
    sys_prompt_bytes = f.read()

with open("scratch/q_block_raw.txt", "rb") as f:
    q_block_bytes = f.read()

with open("scratch/v4_test_raw.txt", "rb") as f:
    v4_test_bytes = f.read()

# 1. Patch context_validator.py
with open(VAL_PATH, "rb") as f:
    val_data = f.read()

val_data = val_data.replace(b'VALIDATOR_VERSION = "v3"', b'VALIDATOR_VERSION = "v4"')
val_data = val_data.replace(b'VALIDATION_METHOD = "QWEN_CONTEXT_V3"', b'VALIDATION_METHOD = "QWEN_CONTEXT_V4"')
val_data = val_data.replace(b'PROMPT_VERSION = "context_validator_v3"', b'PROMPT_VERSION = "context_validator_v4"')

sys_start = val_data.find(b'SYSTEM_PROMPT = """')
sys_end = val_data.find(b'def _normalize_whitespace')
assert sys_start != -1 and sys_end != -1, "Could not locate SYSTEM_PROMPT"
val_data = val_data[:sys_start] + sys_prompt_bytes + b"\n\n\n" + val_data[sys_end:]

q_start = val_data.find(b'# Bounded Question Block')
q_end = val_data.find(b'# Bounded Metadata Header')
assert q_start != -1 and q_end != -1, "Could not locate question_block"
val_data = val_data[:q_start] + q_block_bytes + b"\n\n        " + val_data[q_end:]

with open(VAL_PATH, "wb") as f:
    f.write(val_data)

print("1. context_validator.py patched cleanly.")

# 2. Patch context_validator_service.py
with open(SVC_PATH, "rb") as f:
    svc_data = f.read()

old_trusted = b'''            v3_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v3"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
            ]'''

new_trusted = b'''            v4_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v4"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V4"
            ]

            v3_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v3"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
            ]'''

assert old_trusted in svc_data, "Could not find v3_trusted block"
svc_data = svc_data.replace(old_trusted, new_trusted, 1)

old_prec = b'''            if v3_trusted:
                target_rows = v3_trusted
                val_ver = "v3"
                val_method = "QWEN_CONTEXT_V3"'''

new_prec = b'''            if v4_trusted:
                target_rows = v4_trusted
                val_ver = "v4"
                val_method = "QWEN_CONTEXT_V4"
            elif v3_trusted:
                target_rows = v3_trusted
                val_ver = "v3"
                val_method = "QWEN_CONTEXT_V3"'''

assert old_prec in svc_data, "Could not find v3_trusted precedence"
svc_data = svc_data.replace(old_prec, new_prec, 1)

with open(SVC_PATH, "wb") as f:
    f.write(svc_data)

print("2. context_validator_service.py patched cleanly.")

# 3. Patch test_context_validator_semantics_v2.py
with open(V2_TEST_PATH, "rb") as f:
    v2_data = f.read()

v2_data = v2_data.replace(b'assert res["validation_method"] == "QWEN_CONTEXT_V2"', b'assert res["validation_method"] in ("QWEN_CONTEXT_V2", "QWEN_CONTEXT_V4")')
v2_data = v2_data.replace(b'assert res["validator_version"] == "v2"', b'assert res["validator_version"] in ("v2", "v4")')
v2_data = v2_data.replace(b'assert res["validator_version"] == VALIDATOR_VERSION == "v2"', b'assert res["validator_version"] == VALIDATOR_VERSION')
v2_data = v2_data.replace(b'assert res["validation_method"] == VALIDATION_METHOD == "QWEN_CONTEXT_V2"', b'assert res["validation_method"] == VALIDATION_METHOD')

with open(V2_TEST_PATH, "wb") as f:
    f.write(v2_data)

print("3. test_context_validator_semantics_v2.py patched.")

# 4. Patch test_context_validator_v3_trust_boundary.py
with open(V3_TEST_PATH, "rb") as f:
    v3_data = f.read()

v3_data = v3_data.replace(b'assert VALIDATOR_VERSION == "v3"', b'assert VALIDATOR_VERSION in ("v3", "v4")')
v3_data = v3_data.replace(b'assert VALIDATION_METHOD == "QWEN_CONTEXT_V3"', b'assert VALIDATION_METHOD in ("QWEN_CONTEXT_V3", "QWEN_CONTEXT_V4")')
v3_data = v3_data.replace(b'assert PROMPT_VERSION == "context_validator_v3"', b'assert PROMPT_VERSION in ("context_validator_v3", "context_validator_v4")')

with open(V3_TEST_PATH, "wb") as f:
    f.write(v3_data)

print("4. test_context_validator_v3_trust_boundary.py patched.")

# 5. Write test_context_validator_v4_decision_boundary.py
with open(V4_TEST_PATH, "wb") as f:
    f.write(v4_test_bytes)

print("5. tests/test_context_validator_v4_decision_boundary.py created.")
