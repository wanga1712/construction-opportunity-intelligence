#!/usr/bin/env bash
set -euo pipefail

stage=/tmp/full_normalization_authority_20261113
backup="/opt/CRM_Streamlit/backups/full_normalization_authority_20261113_$(date +%H%M%S)"
target_authority=/opt/tender_documents_research/document_processor/estimate_row_normalization_authority.py
target_resolver=/opt/tender_documents_research/scripts/resolve_estimate_row_categories.py
target_backfill=/opt/tender_documents_research/scripts/backfill_normalization_authority.py

[[ "$(sha256sum "$target_resolver" | awk '{print $1}')" == \
   24b064238dc76b85cd3b3857d5c28abd0c8b4f9dac8a888b4f74a8364b84d528 ]]
[[ ! -e "$target_authority" ]]
[[ ! -e "$target_backfill" ]]

sudo mkdir -p "$backup"
sudo cp -p "$target_resolver" "$backup/resolve_estimate_row_categories.py"
sudo chown -R "$(id -un):$(id -gn)" "$backup"
sed -i 's/\r$//' \
  "$stage/estimate_row_normalization_authority.py" \
  "$stage/resolve_estimate_row_categories.py" \
  "$stage/backfill_normalization_authority.py"

/opt/tender_documents_research/.venv/bin/python -m py_compile \
  "$stage/estimate_row_normalization_authority.py" \
  "$stage/resolve_estimate_row_categories.py" \
  "$stage/backfill_normalization_authority.py"

rollback() {
  status=$?
  if (( status == 0 )); then return; fi
  sudo cp -p "$backup/resolve_estimate_row_categories.py" "$target_resolver"
  sudo rm -f "$target_authority" "$target_backfill"
  echo "FULL_NORMALIZATION_AUTHORITY_ROLLED_BACK backup=$backup status=$status" >&2
}
trap rollback EXIT

sudo install -o sergey -g sergey -m 664 \
  "$stage/estimate_row_normalization_authority.py" "$target_authority.tmp.$$"
sudo install -o sergey -g sergey -m 775 \
  "$stage/resolve_estimate_row_categories.py" "$target_resolver.tmp.$$"
sudo install -o sergey -g sergey -m 775 \
  "$stage/backfill_normalization_authority.py" "$target_backfill.tmp.$$"
sudo mv -f "$target_authority.tmp.$$" "$target_authority"
sudo mv -f "$target_resolver.tmp.$$" "$target_resolver"
sudo mv -f "$target_backfill.tmp.$$" "$target_backfill"

(
  cd /opt/tender_documents_research
  .venv/bin/python -c 'import runpy; from document_processor.estimate_row_normalization_authority import NORMALIZER_VERSION, normalization_state; runpy.run_path("scripts/resolve_estimate_row_categories.py", run_name="verify_import"); runpy.run_path("scripts/backfill_normalization_authority.py", run_name="verify_import")'
)
sha256sum "$target_authority" "$target_resolver" "$target_backfill" \
  | tee "$backup/SHA256SUMS"
trap - EXIT
echo "FULL_NORMALIZATION_AUTHORITY_OK backup=$backup"
