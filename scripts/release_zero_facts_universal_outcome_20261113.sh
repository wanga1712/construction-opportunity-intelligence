#!/usr/bin/env bash
set -euo pipefail

stage=/tmp/crm_release_20261113_post_parse
backup="/opt/CRM_Streamlit/backups/zero_facts_universal_outcome_20261113_$(date +%H%M%S)"
target_parse=/opt/tender_documents_research/document_processor/parse_extractors.py
target_persistence=/opt/tender_documents_research/document_processor/embedded_persistence.py

[[ "$(sha256sum "$target_parse" | awk '{print $1}')" == \
   68556681eafa3e9c848f919e8a046b47146f93f2c318b53d2174ab9c1c54949b ]]
[[ "$(sha256sum "$target_persistence" | awk '{print $1}')" == \
   4a60519164bec7d8b4f72f02f3eb0ba3269db349550e6374de0b4fb1ad659465 ]]

sudo mkdir -p "$backup"
sudo cp -p "$target_parse" "$backup/parse_extractors.py"
sudo cp -p "$target_persistence" "$backup/embedded_persistence.py"
sudo chown -R "$(id -un):$(id -gn)" "$backup"
sed -i 's/\r$//' "$stage/parse_extractors.py" "$stage/embedded_persistence.py"
/opt/tender_documents_research/.venv/bin/python -m py_compile \
  "$stage/parse_extractors.py" "$stage/embedded_persistence.py"

rollback() {
  status=$?
  if (( status == 0 )); then return; fi
  sudo cp -p "$backup/parse_extractors.py" "$target_parse"
  sudo cp -p "$backup/embedded_persistence.py" "$target_persistence"
  sudo systemctl restart \
    tender-docs-daemon.service tender-docs-daemon-open.service \
    tender-docs-daemon-open-2.service tender-docs-daemon-open-3.service \
    tender-docs-daemon-awarded.service tender-docs-band-gold-1.service \
    tender-docs-band-gold-2.service tender-docs-band-silver.service \
    tender-docs-band-bronze.service tender-docs-band-wood.service || true
  echo "UNIVERSAL_OUTCOME_RELEASE_ROLLED_BACK backup=$backup status=$status" >&2
}
trap rollback EXIT

sudo install -o sergey -g sergey -m 664 \
  "$stage/parse_extractors.py" "$target_parse.tmp.$$"
sudo install -o sergey -g sergey -m 664 \
  "$stage/embedded_persistence.py" "$target_persistence.tmp.$$"
sudo mv -f "$target_parse.tmp.$$" "$target_parse"
sudo mv -f "$target_persistence.tmp.$$" "$target_persistence"

(
  cd /opt/tender_documents_research
  .venv/bin/python -c 'from document_processor.embedded_persistence import UNIVERSAL_ROWS_PERSISTED_NOT_NORMALIZED; from document_processor.parse_extractors import extract_and_persist'
)
sudo systemctl restart \
  tender-docs-daemon.service tender-docs-daemon-open.service \
  tender-docs-daemon-open-2.service tender-docs-daemon-open-3.service \
  tender-docs-daemon-awarded.service tender-docs-band-gold-1.service \
  tender-docs-band-gold-2.service tender-docs-band-silver.service \
  tender-docs-band-bronze.service tender-docs-band-wood.service
systemctl is-active --quiet \
  tender-docs-daemon.service tender-docs-daemon-open.service \
  tender-docs-daemon-open-2.service tender-docs-daemon-open-3.service \
  tender-docs-daemon-awarded.service tender-docs-band-gold-1.service \
  tender-docs-band-gold-2.service tender-docs-band-silver.service \
  tender-docs-band-bronze.service tender-docs-band-wood.service

sha256sum "$target_parse" "$target_persistence" | tee "$backup/SHA256SUMS"
trap - EXIT
echo "UNIVERSAL_OUTCOME_RELEASE_OK backup=$backup"
