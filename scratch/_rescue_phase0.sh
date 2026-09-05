#!/bin/bash
set -eu
cd /opt/CRM_Streamlit

echo "=== PHASE 0: PROVE BASE LINEAGE ==="

echo -n "WORKSET_94ce4f4_ANCESTOR_OF_c5db3ad="
git merge-base --is-ancestor 94ce4f4 c5db3ad && echo "YES" || echo "NO"

echo -n "CATEGORY_GATE_b9c45be_IN_BASE="
git merge-base --is-ancestor b9c45be c5db3ad && echo "YES" || echo "NO"

echo -n "OBJECT_MODE_afa14ed_IN_BASE="
git merge-base --is-ancestor afa14ed c5db3ad && echo "YES" || echo "NO"

echo -n "COMMERCIAL_MEDAL_6b38299_IN_BASE="
git merge-base --is-ancestor 6b38299 c5db3ad && echo "YES" || echo "NO"

echo "PHASE_0=DONE"
