import hashlib

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

f1 = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/research_ui_projection.py"
f2 = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/stage_workspace.py"

print("PROJECTION_SHA256:", sha256_file(f1))
print("WORKSPACE_SHA256:", sha256_file(f2))
