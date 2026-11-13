#!/usr/bin/env bash
set -euo pipefail

stage=/tmp/crm_release_20261113_post_parse
backup="/opt/CRM_Streamlit/backups/post_parse_queue_kiosk_20261113_$(date +%H%M%S)"

declare -A target=(
  [parse_extractors.py]=/opt/tender_documents_research/document_processor/parse_extractors.py
  [embedded_persistence.py]=/opt/tender_documents_research/document_processor/embedded_persistence.py
  [document_queue_reconciliation.py]=/opt/CRM_Streamlit/src/services/commercial_routing_v3/document_queue_reconciliation.py
  [reconciliation_document_plan.py]=/opt/CRM_Streamlit/src/services/commercial_routing_v3/reconciliation_document_plan.py
  [reconciliation_queue_writer.py]=/opt/CRM_Streamlit/src/services/commercial_routing_v3/reconciliation_queue_writer.py
  [s13_dashboard3.py]=/usr/local/bin/s13_dashboard3.py
)

declare -A preimage=(
  [parse_extractors.py]=742916277e7f0a09f0032d6fc5e99feba81a335e598c830a85739573446d0a50
  [embedded_persistence.py]=91be6b7dc3335393fdb14991e21d2c368c11c9df08ef22314929a79332ca3eac
  [document_queue_reconciliation.py]=6b0cdfc3f55fd1f303986b981671a60ec8c80c522b33b13f9d9af9cf94e433b1
  [reconciliation_document_plan.py]=64e1918ac5ccf0a7b0203d6d22069969f30880996c7acd63ff6a5f4d1d329c15
  [reconciliation_queue_writer.py]=4ac0a431329ed768111db706876e7d8f2638e450f577768522dc2c07ea4b8b86
  [s13_dashboard3.py]=696b97b2314f4916c18ea2ea35efa8cd3469f35ee38748453f6080fba5ce3146
)

order=(
  parse_extractors.py
  embedded_persistence.py
  document_queue_reconciliation.py
  reconciliation_document_plan.py
  reconciliation_queue_writer.py
  s13_dashboard3.py
)

sudo mkdir -p "$backup"
for name in "${order[@]}"; do
  actual=$(sha256sum "${target[$name]}" | awk '{print $1}')
  if [[ "$actual" != "${preimage[$name]}" ]]; then
    echo "PREIMAGE_MISMATCH $name expected=${preimage[$name]} actual=$actual" >&2
    exit 1
  fi
  sudo cp -p "${target[$name]}" "$backup/$name"
done
sudo chown -R "$(id -un):$(id -gn)" "$backup"

for name in "${order[@]}"; do
  sed -i 's/\r$//' "$stage/$name"
done

/opt/tender_documents_research/.venv/bin/python -m py_compile \
  "$stage/parse_extractors.py" \
  "$stage/embedded_persistence.py"
/opt/CRM_Streamlit/.venv313/bin/python -m py_compile \
  "$stage/document_queue_reconciliation.py" \
  "$stage/reconciliation_document_plan.py" \
  "$stage/reconciliation_queue_writer.py"
python3 -m py_compile "$stage/s13_dashboard3.py"

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
    tender-docs-band-bronze.service tender-docs-band-wood.service \
    s13-dashboard3.service || true
  echo "RELEASE_ROLLED_BACK backup=$backup status=$status" >&2
}
trap rollback EXIT

for name in "${order[@]}"; do
  mode=$(stat -c '%a' "${target[$name]}")
  owner=$(stat -c '%U:%G' "${target[$name]}")
  sudo install -o "${owner%:*}" -g "${owner#*:}" -m "$mode" \
    "$stage/$name" "${target[$name]}.tmp.$$"
  sudo mv -f "${target[$name]}.tmp.$$" "${target[$name]}"
  replaced+=("$name")
done

for name in "${order[@]}"; do
  staged=$(sha256sum "$stage/$name" | awk '{print $1}')
  live=$(sha256sum "${target[$name]}" | awk '{print $1}')
  if [[ "$staged" != "$live" ]]; then
    echo "POSTIMAGE_MISMATCH $name staged=$staged live=$live" >&2
    exit 1
  fi
done

(
  cd /opt/tender_documents_research
  PYTHONPATH=/opt/tender_documents_research:/opt/CRM_Streamlit \
    .venv/bin/python -c 'import document_processor.parse_extractors, document_processor.embedded_persistence'
)
(
  cd /opt/CRM_Streamlit
  .venv313/bin/python -c 'import src.services.commercial_routing_v3.document_queue_reconciliation, src.services.commercial_routing_v3.reconciliation_document_plan, src.services.commercial_routing_v3.reconciliation_queue_writer'
)

sudo systemctl restart \
  tender-docs-daemon.service tender-docs-daemon-open.service \
  tender-docs-daemon-open-2.service tender-docs-daemon-open-3.service \
  tender-docs-daemon-awarded.service tender-docs-band-gold-1.service \
  tender-docs-band-gold-2.service tender-docs-band-silver.service \
  tender-docs-band-bronze.service tender-docs-band-wood.service \
  s13-dashboard3.service

systemctl is-active --quiet \
  tender-docs-daemon.service tender-docs-daemon-open.service \
  tender-docs-daemon-open-2.service tender-docs-daemon-open-3.service \
  tender-docs-daemon-awarded.service tender-docs-band-gold-1.service \
  tender-docs-band-gold-2.service tender-docs-band-silver.service \
  tender-docs-band-bronze.service tender-docs-band-wood.service \
  s13-dashboard3.service

ready=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 2 http://127.0.0.1:8897/api/metrics >/dev/null; then
    ready=1
    break
  fi
  sleep 0.5
done
if (( ready != 1 )); then
  echo "DASHBOARD_HTTP_NOT_READY" >&2
  exit 1
fi

for name in "${order[@]}"; do
  sha256sum "${target[$name]}"
done | tee "$backup/SHA256SUMS"

trap - EXIT
echo "RELEASE_OK backup=$backup"
