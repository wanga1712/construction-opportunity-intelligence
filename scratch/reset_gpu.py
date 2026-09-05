import json
p = '/var/lib/crm-v3-canary/gpu_arbiter/state.json'
d = json.loads(open(p).read())
d['GPU_QUEUE_ROUTING_DEPTH'] = 0
open(p, 'w').write(json.dumps(d, indent=2))
print("GPU queue reset to 0.")
