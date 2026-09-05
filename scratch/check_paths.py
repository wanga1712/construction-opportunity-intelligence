import json
with open('/tmp/failed_v3_quarantine.json') as f:
    d = json.load(f)
for table, data in d.items():
    print(table, "count:", data.get("count"))
    sample = data.get("sample", [])
    if sample:
        print("  Sample keys:", list(sample[0].keys()))
        for r in sample[:3]:
            if "local_path" in r:
                print("  local_path:", r["local_path"])
