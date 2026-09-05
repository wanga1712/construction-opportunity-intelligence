#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 15B: CLEAN PYCACHE AND AMEND ==="

# Add gitignore
cat > .gitignore << 'GI'
__pycache__/
*.pyc
*.pyo
.env
*.egg-info/
.pytest_cache/
GI

git rm -r --cached '**/__pycache__' 2>/dev/null || true
git rm --cached .env 2>/dev/null || true
git add .gitignore
git add -A

git commit --amend --no-edit 2>&1

echo "RESCUE_HEAD=$(git rev-parse HEAD)"
echo "RESCUE_GIT_DIRTY=$(git status --porcelain | wc -l)"

echo "=== PHASE 16: PRODUCTION CUTOVER ==="

BACKUP_ROOT=$(ls -td /opt/backups/crm_rescue_* 2>/dev/null | head -1)
echo "BACKUP_ROOT=$BACKUP_ROOT"

echo "--- Save current service unit ---"
systemctl cat crm-streamlit.service > "$BACKUP_ROOT/crm-streamlit.service.before-rescue.txt" 2>&1

echo "--- Current service WorkingDirectory ---"
grep WorkingDirectory /etc/systemd/system/crm-streamlit.service

echo "--- Current service ExecStart ---"
grep ExecStart /etc/systemd/system/crm-streamlit.service

echo "--- Stop crm-streamlit.service ---"
sudo systemctl stop crm-streamlit.service
sleep 2
echo "SERVICE_STOPPED=$(systemctl is-active crm-streamlit.service 2>/dev/null || echo yes)"

echo "--- Update WorkingDirectory to rescue ---"
sudo sed -i 's|WorkingDirectory=/opt/CRM_Streamlit|WorkingDirectory=/opt/CRM_Streamlit_rescue|' /etc/systemd/system/crm-streamlit.service

echo "--- Update PYTHONPATH in service environment ---"
# Check if PYTHONPATH in env file or in unit
grep -n 'PYTHONPATH' /etc/systemd/system/crm-streamlit.service || echo "NO_PYTHONPATH_IN_UNIT"

# Update PYTHONPATH env in unit
sudo sed -i 's|Environment=PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89|Environment=PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89|' /etc/systemd/system/crm-streamlit.service

echo "--- Verify updated unit ---"
grep WorkingDirectory /etc/systemd/system/crm-streamlit.service
grep PYTHONPATH /etc/systemd/system/crm-streamlit.service
grep ExecStart /etc/systemd/system/crm-streamlit.service

echo "--- daemon-reload ---"
sudo systemctl daemon-reload

echo "--- Start crm-streamlit.service ---"
sudo systemctl start crm-streamlit.service
sleep 3

echo "--- Post-start status ---"
systemctl is-active crm-streamlit.service
systemctl status crm-streamlit.service --no-pager 2>&1 | head -20

echo "PHASE_15B_16=DONE"
