#!/usr/bin/env bash
set -euo pipefail

target=/usr/local/bin/s13_dashboard3.py
staged=/tmp/crm_release_20261113_post_parse/s13_dashboard3.py
expected=47946de149247b4a12f1623e2f2d1820f7b6c9dd766b358ab020b516d7020874
backup="/opt/CRM_Streamlit/backups/kiosk_null_signal_20261113_$(date +%H%M%S)"

[[ "$(sha256sum "$target" | awk '{print $1}')" == "$expected" ]]
sudo mkdir -p "$backup"
sudo cp -p "$target" "$backup/s13_dashboard3.py"
sudo chown -R "$(id -un):$(id -gn)" "$backup"
sed -i 's/\r$//' "$staged"
python3 -m py_compile "$staged"

rollback() {
  status=$?
  if (( status == 0 )); then return; fi
  sudo cp -p "$backup/s13_dashboard3.py" "$target"
  sudo systemctl restart s13-dashboard3.service || true
  echo "KIOSK_NULL_SIGNAL_ROLLED_BACK backup=$backup status=$status" >&2
}
trap rollback EXIT

sudo install -o root -g root -m 755 "$staged" "$target.tmp.$$"
sudo mv -f "$target.tmp.$$" "$target"
sudo systemctl restart s13-dashboard3.service

ready=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 2 http://127.0.0.1:8897/api/metrics >/dev/null; then
    ready=1
    break
  fi
  sleep 0.5
done
(( ready == 1 ))
sha256sum "$target" | tee "$backup/SHA256SUMS"
trap - EXIT
echo "KIOSK_NULL_SIGNAL_OK backup=$backup"
