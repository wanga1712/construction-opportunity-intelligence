import json

# Show the contract 2770780719026000028 in both snapshots
old = json.load(open('/tmp/eis_s13_parity_work/old_run.json'))
new = json.load(open('/tmp/eis_s13_parity_work/new_run.json'))

c2 = '2770780719026000028'
print("OLD 2770:", old['snapshot']['registry'].get(c2))
print("NEW 2770:", new['snapshot']['registry'].get(c2))

# Also check seed snapshot
seed = json.load(open('/tmp/eis_s13_parity_work/seed_snap.json')) if __import__('os').path.exists('/tmp/eis_s13_parity_work/seed_snap.json') else None
if seed:
    print("SEED 0373:", seed['registry'].get('0373200081226000248'))
    print("SEED 2770:", seed['registry'].get(c2))
