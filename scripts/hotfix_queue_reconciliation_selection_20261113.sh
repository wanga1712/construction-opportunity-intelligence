#!/usr/bin/env bash
set -euo pipefail

target=/opt/CRM_Streamlit/src/services/commercial_routing_v3/document_queue_reconciliation.py
staged=/tmp/crm_release_20261113_post_parse/document_queue_reconciliation.py
expected=f3b5af0207e0b2ae09c975b15dd166d0e9a007693fe38652d7d4becb2e36a81f
backup="/opt/CRM_Streamlit/backups/post_parse_queue_kiosk_20261113_$(date +%H%M%S)"

actual=$(sha256sum "$target" | awk '{print $1}')
if [[ "$actual" != "$expected" ]]; then
  echo "PREIMAGE_MISMATCH expected=$expected actual=$actual" >&2
  exit 1
fi

sudo mkdir -p "$backup"
sudo cp -p "$target" "$backup/document_queue_reconciliation.py"
sudo chown -R "$(id -un):$(id -gn)" "$backup"

sed -i 's/\r$//' "$staged"
/opt/CRM_Streamlit/.venv313/bin/python -m py_compile "$staged"
sudo install -o sergey -g sergey -m 664 "$staged" "$target.tmp.$$"
sudo mv -f "$target.tmp.$$" "$target"

if ! (
  cd /opt/CRM_Streamlit
  .venv313/bin/python -c 'import src.services.commercial_routing_v3.document_queue_reconciliation'
); then
  sudo cp -p "$backup/document_queue_reconciliation.py" "$target"
  exit 1
fi

sha256sum "$target" | tee "$backup/SHA256SUMS"
echo "HOTFIX_OK backup=$backup"
