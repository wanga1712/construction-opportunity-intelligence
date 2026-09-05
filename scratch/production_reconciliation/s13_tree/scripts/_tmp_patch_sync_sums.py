#!/usr/bin/env python3
import json
import re
import subprocess
from pathlib import Path

OUT = Path("/var/lib/crm-v3-canary/production_runtime_report_20260816")
raw = subprocess.check_output(
    "journalctl -u crm-procurement-sync.service --since '2026-08-14 23:00:00' --no-pager -o cat",
    shell=True,
    text=True,
)
lines = [ln for ln in raw.splitlines() if "run_crm_sync: Sync result:" in ln]
ins = upd = err = 0
for ln in lines:
    m = re.search(r"'inserted':\s*(\d+)", ln)
    u = re.search(r"'updated':\s*(\d+)", ln)
    e = re.search(r"'errors':\s*(\d+)", ln)
    if m:
        ins += int(m.group(1))
    if u:
        upd += int(u.group(1))
    if e:
        err += int(e.group(1))

sync = json.loads((OUT / "sync_activity.json").read_text(encoding="utf-8"))
sync.update(
    {
        "SYNC_SUCCESS": len(lines),
        "SOURCE_ROWS_INSERTED_SUM_FROM_JOURNAL": ins,
        "SOURCE_ROWS_UPDATED_SUM_FROM_JOURNAL": upd,
        "SOURCE_ROWS_UPDATED_NOTE": (
            "Almost all CRM rows are touched each 15m sync; NOT material business changes. "
            "Use inserted sum as NEW_PROCUREMENTS_IMPORTED proxy."
        ),
        "NEW_PROCUREMENTS_IMPORTED_PROXY_INSERTED_SUM": ins,
        "SYNC_ERRORS_SUM": err,
        "sync_result_lines": len(lines),
    }
)
(OUT / "sync_activity.json").write_text(
    json.dumps(sync, indent=2, ensure_ascii=False), encoding="utf-8"
)
full = json.loads((OUT / "production_runtime_full.json").read_text(encoding="utf-8"))
full["sync"] = sync
(OUT / "production_runtime_full.json").write_text(
    json.dumps(full, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
)
# patch summary table lines
md = (OUT / "production_runtime_summary.md").read_text(encoding="utf-8")
md = md.replace(
    "| SOURCE_ROWS_INSERTED_SUM | None |",
    f"| SOURCE_ROWS_INSERTED_SUM | {ins} |",
).replace(
    "| SOURCE_ROWS_UPDATED_SUM | None |",
    f"| SOURCE_ROWS_UPDATED_SUM | {upd} (mostly non-material touches) |",
)
(OUT / "production_runtime_summary.md").write_text(md, encoding="utf-8")
print(json.dumps({"runs": len(lines), "inserted": ins, "updated": upd, "errors": err}, indent=2))
