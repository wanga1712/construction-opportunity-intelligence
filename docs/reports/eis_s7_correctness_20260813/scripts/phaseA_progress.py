#!/usr/bin/env python3
import json
from pathlib import Path

p = Path("/tmp/eis_correctness_20260813/progress.jsonl")
if not p.exists():
    print("NO_PROGRESS")
    raise SystemExit(0)
rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
zips = sum(int(r.get("zips") or 0) for r in rows)
xml = sum(int(r.get("xml") or 0) for r in rows)
err = sum(1 for r in rows if "error" in r.get("event", ""))
done = [r for r in rows if r.get("event") == "contour_done"]
regions = sorted({str(r.get("region")) for r in done if r.get("region")})
print(
    json.dumps(
        {
            "events": len(rows),
            "contour_done": len(done),
            "regions": len(regions),
            "zips": zips,
            "xml": xml,
            "errors": err,
            "last": rows[-1],
            "finished": any(r.get("event") == "finished" for r in rows),
        },
        ensure_ascii=False,
    )
)
