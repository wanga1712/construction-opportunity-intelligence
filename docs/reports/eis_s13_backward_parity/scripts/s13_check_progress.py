import json
with open('/opt/tendermonitor/backward/region_progress.json') as f:
    d = json.load(f)
for date in sorted(d.keys()):
    r = d[date]['processed_regions']
    print(f"{date}: {len(r)}/55 regions")
