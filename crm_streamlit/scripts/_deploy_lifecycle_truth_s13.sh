#!/bin/bash
set -euo pipefail
BRANCH="CRM-V3-LIFECYCLE-TRUTH-SOURCE-FILTER-AND-AI-DECISION-VISIBILITY-1"
REPO="/opt/CRM_Streamlit"
TMP="/tmp/crm_lifecycle_overlay_$$"
cd "$REPO"
echo "PRE_HEAD=$(git rev-parse HEAD 2>/dev/null || true)"
systemctl is-active crm-streamlit || true
mkdir -p "$TMP"
cd "$TMP"
git init -q
git remote add origin https://github.com/wanga1712/construction-opportunity-intelligence.git
git fetch --depth 1 origin "$BRANCH"
git archive FETCH_HEAD crm_streamlit | tar -x --strip-components=1
FETCH_SHA=$(git rev-parse FETCH_HEAD)
echo "FETCH_SHA=$FETCH_SHA"
rsync -a --exclude '.git' --exclude '.venv*' --exclude '__pycache__' --exclude '*.pyc' --exclude '.env' ./ "$REPO/"
echo "$BRANCH $FETCH_SHA" | tee /tmp/crm_deployed_lifecycle_truth.txt
cd "$REPO"
sudo systemctl restart crm-streamlit
sleep 4
systemctl is-active crm-streamlit
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8504/
.venv313/bin/python - <<'PY'
from pathlib import Path
assert Path("src/services/effective_lifecycle.py").exists()
assert Path("src/services/ai_decision_summary.py").exists()
tabs = Path("src/ui/components/analytics_v2/tabs.py").read_text(encoding="utf-8")
assert "_render_law_filter" in tabs and "factual_open_torgi_sql" in tabs
ws = Path("src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
assert "_render_ai_decision_block" in ws
print("RUNTIME_SOURCE_CONTRACT=PASS")
PY
.venv313/bin/python -m pytest \
  tests/test_lifecycle_truth_and_ai_visibility.py \
  tests/test_fast_category_triage.py \
  tests/test_annotation_staged.py \
  tests/test_analytics_stage_workspace.py \
  -q --tb=line
rm -rf "$TMP"
echo "DEPLOY_DONE"
