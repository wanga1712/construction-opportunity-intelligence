#!/bin/bash
set -euo pipefail
export PATH="/opt/tendermonitor/venv/bin:/usr/bin:/bin:$PATH"
PY=/opt/tendermonitor/venv/bin/python
if ! test -x "$PY"; then PY=python3; fi

sudo rm -rf /tmp/eis_s13_parity_old /tmp/eis_s13_parity_git
sudo mkdir -p /tmp/eis_s13_parity_old /tmp/eis_s13_parity_git/eis_ingestion
sudo tar -xzf /tmp/eis_s13_parity_old.tgz -C /tmp/eis_s13_parity_old
sudo tar -xzf /tmp/s13_backfill.tgz -C /tmp/eis_s13_parity_git/eis_ingestion
test -f /tmp/eis_s13_parity_old/parsing_xml/okpd_parser.py && echo OLD_OKPD=YES
test ! -f /tmp/eis_s13_parity_old/parsing_xml/rgk_batch.py && echo OLD_RGK_BATCH=NO
test -f /tmp/eis_s13_parity_git/eis_ingestion/s13_backfill/parsing_xml/rgk_batch.py && echo GIT_RGK_BATCH=YES
sudo chown -R postgres:postgres /tmp/eis_s13_parity_old /tmp/eis_s13_parity_git
sudo rm -rf /tmp/eis_s13_parity_work
sudo mkdir -p /tmp/eis_s13_parity_work
sudo mkdir -p /tmp/eis_s13_parity_work/logs
sudo chown -R postgres:postgres /tmp/eis_s13_parity_work
echo RGK_XML=$(find /tmp/eis_s13_parity/rgk -maxdepth 1 -name '*.xml' | wc -l)
echo PY=$PY
sudo -n -u postgres env \
  HOME=/tmp/eis_s13_parity_work \
  TENDERMONITOR_LOG_DIR=/tmp/eis_s13_parity_work/logs \
  PATH="/opt/tendermonitor/venv/bin:/usr/bin:/bin" \
  PYTHONUNBUFFERED=1 \
  "$PY" /tmp/isolated_db_rgk_replay.py
