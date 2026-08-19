#!/bin/bash
set -euo pipefail
cd /opt/tendermonitor
rm -f /tmp/eis_s13_parity_old.tgz
tar -czf /tmp/eis_s13_parity_old.tgz \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.env' \
  --exclude='*.env.*' \
  --exclude='*credintials*' \
  --exclude='*.bak' \
  --exclude='*.bak.*' \
  --exclude='*.orig' \
  parsing_xml database_work utils file_delete required_tags secondary_functions.py
python3 - <<'PY'
import tarfile
archive = tarfile.open("/tmp/eis_s13_parity_old.tgz", "r:gz")
names = archive.getnames()
bad = [name for name in names if "credintial" in name.lower() or name.endswith(".env") or ".bak" in name]
print("OLD_TGZ_FILES=" + str(len(names)))
print("OLD_TGK_HAS_RGK_BATCH=" + ("YES" if any(n.endswith("rgk_batch.py") for n in names) else "NO"))
print("OLD_TGZ_HAS_OKPD=" + ("YES" if any(n.endswith("okpd_parser.py") for n in names) else "NO"))
print("OLD_TGZ_SECRET_FILES=" + str(len(bad)))
for name in bad:
    print("SECRET=" + name)
PY
wc -c /tmp/eis_s13_parity_old.tgz | awk '{print "OLD_TGZ_BYTES="$1}'
