#!/usr/bin/env bash
set -euo pipefail

stage=/tmp/crm_release_20261113_post_parse
backup="/opt/CRM_Streamlit/backups/zero_facts_stage_counters_20261113_$(date +%H%M%S)"

declare -A target=(
  [parse_extractors.py]=/opt/tender_documents_research/document_processor/parse_extractors.py
  [embedded_persistence.py]=/opt/tender_documents_research/document_processor/embedded_persistence.py
)
declare -A preimage=(
  [parse_extractors.py]=b0d979f171df1827f6883d410404617f5853042675194817913315c1575a8b3a
  [embedded_persistence.py]=57aaece5824b244a0db210914846694f1f59daa94048f24e67272c02bf56c241
)

sudo mkdir -p "$backup"
replaced=()
rollback() {
  status=$?
  if (( status == 0 )); then
    return
  fi
  for name in "${replaced[@]}"; do
    sudo cp -p "$backup/$name" "${target[$name]}"
  done
  sudo systemctl restart \
    tender-docs-daemon.service tender-docs-daemon-open.service \
    tender-docs-daemon-open-2.service tender-docs-daemon-open-3.service \
    tender-docs-daemon-awarded.service tender-docs-band-gold-1.service \
    tender-docs-band-gold-2.service tender-docs-band-silver.service \
    tender-docs-band-bronze.service tender-docs-band-wood.service || true
  echo "STAGE_COUNTER_RELEASE_ROLLED_BACK backup=$backup status=$status" >&2
}
trap rollback EXIT

for name in parse_extractors.py embedded_persistence.py; do
  actual=$(sha256sum "${target[$name]}" | awk '{print $1}')
  if [[ "$actual" != "${preimage[$name]}" ]]; then
    echo "PREIMAGE_MISMATCH $name expected=${preimage[$name]} actual=$actual" >&2
    exit 1
  fi
  sudo cp -p "${target[$name]}" "$backup/$name"
  sed -i 's/\r$//' "$stage/$name"
done
sudo chown -R "$(id -un):$(id -gn)" "$backup"

/opt/tender_documents_research/.venv/bin/python -m py_compile \
  "$stage/parse_extractors.py" "$stage/embedded_persistence.py"

for name in parse_extractors.py embedded_persistence.py; do
  sudo install -o sergey -g sergey -m 664 \
    "$stage/$name" "${target[$name]}.tmp.$$"
  sudo mv -f "${target[$name]}.tmp.$$" "${target[$name]}"
  replaced+=("$name")
done

for name in parse_extractors.py embedded_persistence.py; do
  staged=$(sha256sum "$stage/$name" | awk '{print $1}')
  live=$(sha256sum "${target[$name]}" | awk '{print $1}')
  if [[ "$staged" != "$live" ]]; then
    echo "POSTIMAGE_MISMATCH $name staged=$staged live=$live" >&2
    exit 1
  fi
done

(
  cd /opt/tender_documents_research
  .venv/bin/python -c 'from document_processor.embedded_persistence import PersistenceResult, NO_RAW_FACTS, RAW_FACTS_FILTERED; from document_processor.parse_extractors import _persist_embedded'
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

for name in parse_extractors.py embedded_persistence.py; do
  sha256sum "${target[$name]}"
done | tee "$backup/SHA256SUMS"

trap - EXIT
echo "STAGE_COUNTER_RELEASE_OK backup=$backup"
