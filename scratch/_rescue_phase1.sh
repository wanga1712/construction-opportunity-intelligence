#!/bin/bash
set -eu
cd /opt/CRM_Streamlit

echo "=== PHASE 1: PRESERVE ALL LOCAL S13 HISTORY ==="

TS=$(date +%Y%m%d_%H%M%S)
BACKUP_ROOT="/opt/backups/crm_rescue_${TS}"
mkdir -p "$BACKUP_ROOT"
echo "BACKUP_ROOT=$BACKUP_ROOT"

echo "--- Creating git bundle ---"
git bundle create "$BACKUP_ROOT/CRM_Streamlit_all_refs.bundle" --all 2>&1
echo "BUNDLE_CREATED=YES"

echo "--- Saving metadata ---"
git status --porcelain=v1 -uall > "$BACKUP_ROOT/git_status.txt"
git branch -avv > "$BACKUP_ROOT/git_branches.txt"
git log --all --graph --decorate --oneline --date-order -n 500 > "$BACKUP_ROOT/git_graph.txt"
git reflog show --all --date=iso -n 500 > "$BACKUP_ROOT/git_reflog.txt"

echo "--- Saving diffs ---"
git diff > "$BACKUP_ROOT/unstaged.diff"
git diff --cached > "$BACKUP_ROOT/staged.diff"

echo "--- Archiving runtime overlay ---"
tar -czf "$BACKUP_ROOT/current_runtime_overlay.tar.gz" -C /opt/CRM_Streamlit app.py src scripts tests 2>/dev/null || true
echo "CURRENT_RUNTIME_OVERLAY_ARCHIVED=YES"

echo "--- Verifying bundle ---"
git bundle verify "$BACKUP_ROOT/CRM_Streamlit_all_refs.bundle" 2>&1
VERIFY_EXIT=$?
if [ $VERIFY_EXIT -eq 0 ]; then
  echo "LOCAL_HISTORY_BUNDLE_VERIFIED=YES"
else
  echo "LOCAL_HISTORY_BUNDLE_VERIFIED=NO"
fi

echo "--- Backup contents ---"
ls -lh "$BACKUP_ROOT/"

echo "PHASE_1=DONE"
