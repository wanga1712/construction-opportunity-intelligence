import json
old = json.load(open('/tmp/eis_s13_parity_work/old_run.json'))
new = json.load(open('/tmp/eis_s13_parity_work/new_run.json'))
c = '0373200081226000248'
old_r = old['snapshot']['registry'].get(c)
new_r = new['snapshot']['registry'].get(c)
old_u = old['snapshot']['unresolved'].get(c)
new_u = new['snapshot']['unresolved'].get(c)
print('OLD_REGISTRY:', old_r)
print('NEW_REGISTRY:', new_r)
print('OLD_UNRESOLVED:', old_u)
print('NEW_UNRESOLVED:', new_u)
if old_r and new_r:
    for k in set(list(old_r.keys()) + list(new_r.keys())):
        if old_r.get(k) != new_r.get(k):
            print(f"DIFF field={k} OLD={old_r.get(k)!r} NEW={new_r.get(k)!r}")
