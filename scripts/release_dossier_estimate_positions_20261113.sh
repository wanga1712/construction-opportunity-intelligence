#!/usr/bin/env bash
set -euo pipefail

stage=/tmp/dossier_estimate_positions_20261113
backup="/opt/CRM_Streamlit/backups/dossier_estimate_positions_20261113_$(date +%H%M%S)"
target_dossier=/opt/CRM_Streamlit/src/services/procurement_card_dossier_service.py
target_category=/opt/CRM_Streamlit/src/services/procurement_card_category_service.py

[[ "$(sha256sum "$target_dossier" | awk '{print $1}')" == \
   c64c40183127ddea6631fe5b2d8f61ba24529e7f5564746154cc142c8af3028f ]]
[[ "$(sha256sum "$target_category" | awk '{print $1}')" == \
   e2695092684763bcec1d8a5ae4f5baf04af10d2fec1f2579ea0d200ca1e392a8 ]]

sudo mkdir -p "$backup"
sudo cp -p "$target_dossier" "$backup/procurement_card_dossier_service.py"
sudo cp -p "$target_category" "$backup/procurement_card_category_service.py"
sudo chown -R "$(id -un):$(id -gn)" "$backup"
sed -i 's/\r$//' \
  "$stage/procurement_card_dossier_service.py" \
  "$stage/procurement_card_category_service.py"
/opt/CRM_Streamlit/.venv313/bin/python -m py_compile \
  "$stage/procurement_card_dossier_service.py" \
  "$stage/procurement_card_category_service.py"

rollback() {
  status=$?
  if (( status == 0 )); then return; fi
  sudo cp -p "$backup/procurement_card_dossier_service.py" "$target_dossier"
  sudo cp -p "$backup/procurement_card_category_service.py" "$target_category"
  sudo systemctl restart crm-streamlit.service || true
  echo "DOSSIER_POSITIONS_RELEASE_ROLLED_BACK backup=$backup status=$status" >&2
}
trap rollback EXIT

sudo install -o sergey -g sergey -m 664 \
  "$stage/procurement_card_dossier_service.py" "$target_dossier.tmp.$$"
sudo install -o sergey -g sergey -m 664 \
  "$stage/procurement_card_category_service.py" "$target_category.tmp.$$"
sudo mv -f "$target_dossier.tmp.$$" "$target_dossier"
sudo mv -f "$target_category.tmp.$$" "$target_category"

(
  cd /opt/CRM_Streamlit
  .venv313/bin/python -c 'from src.services.procurement_card_dossier_service import load_category_positions; from src.services.procurement_card_category_service import build_category_cards'
)
sudo systemctl restart crm-streamlit.service
systemctl is-active --quiet crm-streamlit.service

ready=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:8504/_stcore/health >/dev/null; then
    ready=1
    break
  fi
  sleep 0.5
done
(( ready == 1 ))

sha256sum "$target_dossier" "$target_category" | tee "$backup/SHA256SUMS"
trap - EXIT
echo "DOSSIER_POSITIONS_RELEASE_OK backup=$backup"
