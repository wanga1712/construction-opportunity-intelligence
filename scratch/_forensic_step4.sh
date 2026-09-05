#!/bin/bash
set -u

echo "=== STEP 4: RUNTIME MODULE PATHS ==="
cd /opt/CRM_Streamlit
/opt/CRM_Streamlit/.venv313/bin/python - <<'PY'
import pathlib
import sys
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/pythonProject89")

mods_found = []
try:
    import src
    p = pathlib.Path(src.__file__).resolve()
    print(f"SRC={p}")
    mods_found.append(("src", p))
except Exception as e:
    print(f"SRC_IMPORT_ERROR={repr(e)}")

try:
    import src.ui.components.analytics_v2.tabs as tabs
    p = pathlib.Path(tabs.__file__).resolve()
    print(f"TABS={p}")
    mods_found.append(("tabs", p))
except Exception as e:
    print(f"TABS_IMPORT_ERROR={repr(e)}")

try:
    import src.ui.components.analytics_v2.annotation_card as ann
    p = pathlib.Path(ann.__file__).resolve()
    print(f"ANNOTATION={p}")
    mods_found.append(("annotation", p))
except Exception as e:
    print(f"ANNOTATION_IMPORT_ERROR={repr(e)}")

try:
    import src.services.expert_annotation_service as expert
    p = pathlib.Path(expert.__file__).resolve()
    print(f"EXPERT={p}")
    mods_found.append(("expert", p))
except Exception as e:
    print(f"EXPERT_IMPORT_ERROR={repr(e)}")

try:
    import src.services.annotation_state_service as states
    p = pathlib.Path(states.__file__).resolve()
    print(f"STATES={p}")
    mods_found.append(("states", p))
except Exception as e:
    print(f"STATES_IMPORT_ERROR={repr(e)}")

try:
    import src.ui.components.analytics_v2.card_compact as card
    p = pathlib.Path(card.__file__).resolve()
    print(f"CARD={p}")
    mods_found.append(("card", p))
except Exception as e:
    print(f"CARD_IMPORT_ERROR={repr(e)}")
PY

echo "=== STEP 5: TRACKED STATUS + SHA256 ==="
cd /opt/CRM_Streamlit

for f in \
  src/services/expert_annotation_service.py \
  src/ui/components/analytics_v2/tabs.py \
  src/ui/components/analytics_v2/annotation_card.py \
  src/ui/components/analytics_v2/card_compact.py \
  src/services/annotation_state_service.py \
  crm_streamlit/src/services/expert_annotation_service.py \
  crm_streamlit/src/ui/components/analytics_v2/tabs.py \
  crm_streamlit/src/ui/components/analytics_v2/annotation_card.py \
  crm_streamlit/src/ui/components/analytics_v2/card_compact.py \
  crm_streamlit/src/services/annotation_state_service.py; do
  if [ -f "$f" ]; then
    tracked="NO"
    git ls-files --error-unmatch "$f" >/dev/null 2>&1 && tracked="YES"
    sha=$(sha256sum "$f" | awk '{print $1}')
    echo "FILE=$f TRACKED=$tracked SHA256=$sha"
  fi
done

echo "=== STEP 5B: GIT ROOT FOR RUNTIME ==="
echo "RUNTIME_GIT_ROOT=$(git -C /opt/CRM_Streamlit/src rev-parse --show-toplevel 2>/dev/null || echo NOT_IN_GIT)"
