#!/usr/bin/env python3
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/phase71_v63_cal.json"
d = json.load(open(path, encoding="utf-8"))
print(json.dumps(d.get("arms"), indent=2, ensure_ascii=False))
rows = d["results"].get("v6_3") or d["results"].get("v6_2") or []
miss = [r for r in rows if r.get("missed")]
fp = [r for r in rows if r.get("false_positive")]
print("MISS", len(miss))
for r in miss:
    print(r["procurement_id"], r.get("expected_exact_category"), r.get("categories"), (r.get("title") or "")[:80])
print("FP", len(fp))
for r in fp:
    print(r["procurement_id"], r.get("categories"), (r.get("title") or "")[:80])
print("mut", d.get("PRODUCTION_ASSESSMENTS_MUTATED"), d.get("PRODUCTION_OPPORTUNITIES_MUTATED"))
