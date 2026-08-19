import json
with open('/opt/tendermonitor/region_progress.json') as f:
    d = json.load(f)
recent = sorted(d.keys())[-1]
print("S7_FORWARD_SOURCE_DATE=" + recent)
print("S7_FORWARD_REGIONS=" + str(len(d[recent]["processed_regions"])) + "/55")
