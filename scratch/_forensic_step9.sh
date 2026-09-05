#!/bin/bash
set -u
cd /opt/CRM_Streamlit

echo "=== STEP 8B: UNREACHABLE SHOW ==="
for sha in 11c36e3f3aed209bbbeca1d11b9cf6fda676228f 2ea38c6efb9c10b0f982c7ed819c4c957e0d7a28 76f497c3b00d95c042a25c0ea4fca68f56398f73; do
  echo "--- $sha ---"
  git show --stat --oneline "$sha" 2>&1 | head -30
done

echo "=== STEP 9: TRACKED UI PATHS ==="
git ls-files | grep -E 'analytics_v2/(tabs|card_compact|annotation_card|stage_workspace)\.py$|analytics_contour_v2_page\.py$|annotation_state_service\.py$|expert_annotation_service\.py$'

echo "=== STEP 9B: FILE HISTORY ==="
for path in $(git ls-files | grep -E 'analytics_v2/(tabs|card_compact|annotation_card)\.py$|annotation_state_service\.py$|expert_annotation_service\.py$'); do
  echo "--- HISTORY: $path ---"
  git log --all --follow --date=iso --format='%H|%ad|%D|%s' -- "$path" | head -30
done

echo "=== STEP 10: ACCEPTANCE EVIDENCE ==="
git log --all --oneline --date=iso --format='%H|%ad|%D|%s' -- 'docs/reports' | head -30

echo "=== STEP 10B: DEPLOY COMMITS ==="
git log --all --oneline --regexp-ignore-case --grep='acceptance\|production\|deploy\|PASS' --date=iso --format='%H|%ad|%D|%s' | head -40

echo "=== STEP 11: PERFORMANCE FIX ==="
git log --all --oneline --regexp-ignore-case --grep='performance\|pagination\|workset\|lazy\|batch\|N+1\|slow' --date=iso --format='%H|%ad|%D|%s' | head -20

echo "=== STEP 12: LEARNING BACKEND TREE ==="
for sha in $(git log --all --oneline --regexp-ignore-case --grep='learning\|autonomous\|experience\|reward' --format='%H' | head -20); do
  has_all="YES"
  for f in autonomous_worker.py autonomous_learning_loop.py reward_ledger_service.py experience_memory.py sparse_dataset_compiler.py; do
    git ls-tree -r "$sha" --name-only | grep -q "$f" || has_all="NO"
  done
  if [ "$has_all" = "YES" ]; then
    echo "LEARNING_TREE_SHA=$sha ALL_PRESENT=YES"
    git log -1 --format='%H|%ad|%s' --date=iso "$sha"
    break
  fi
done
echo "=== DONE ==="
