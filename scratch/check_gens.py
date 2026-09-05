import json
with open('/tmp/failed_v3_quarantine.json') as f:
    d = json.load(f)
for table, data in d.items():
    gens = set()
    for r in data.get('sample', []):
        if 'pipeline_generation' in r:
            gens.add(r['pipeline_generation'])
    print(table, "generations:", list(gens))
