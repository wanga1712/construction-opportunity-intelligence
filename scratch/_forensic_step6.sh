#!/bin/bash
set -u
cd /opt/CRM_Streamlit

echo "=== STEP 6: FETCH AND LOCAL-ONLY COMMITS ==="
git fetch origin --prune 2>&1 || true

echo "--- LOCAL ONLY COMMITS ---"
git log --all --not --remotes=origin --date=iso --format='%H|%ad|%D|%s' --date-order

echo "--- LOCAL ONLY COUNT ---"
COUNT=$(git log --all --not --remotes=origin --oneline | wc -l)
echo "LOCAL_ONLY_COMMITS_COUNT=$COUNT"

echo "=== STEP 7: REFLOG ==="
git reflog show --all --date=iso --decorate -n 300 2>&1 | head -300

echo "=== STEP 8: UNREACHABLE COMMITS ==="
git fsck --full --no-reflogs --unreachable 2>&1 | grep "^unreachable commit" | head -50
