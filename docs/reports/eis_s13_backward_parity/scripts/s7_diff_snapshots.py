import json, os

old = json.load(open('/tmp/eis_s13_parity_work/old_run.json'))
new = json.load(open('/tmp/eis_s13_parity_work/new_run.json'))

# Find all contracts that differ between old and new
compare_fields = ['final_price', 'delivery_start_date', 'delivery_end_date', 'contractor_id', 'okpd_id', 'auction_name', 'lifecycle']
print("All registry keys only in OLD:", list(set(old['snapshot']['registry']) - set(new['snapshot']['registry']))[:10])
print("All registry keys only in NEW:", list(set(new['snapshot']['registry']) - set(old['snapshot']['registry']))[:10])
print()
# Check the seed snap if available
seed_path = '/tmp/eis_s13_parity_work/seed_snap.json'
seed = None
if os.path.exists(seed_path):
    seed = json.load(open(seed_path))
    print("SEED has 0373200081226000248:", '0373200081226000248' in seed.get('registry', {}))
    sr = seed['registry'].get('0373200081226000248')
    print("SEED row:", sr)
else:
    print("No seed_snap.json")

# Show what changed for this contract vs seed
c = '0373200081226000248'
print()
print("OLD final_price:", old['snapshot']['registry'][c].get('final_price'))
print("NEW final_price:", new['snapshot']['registry'][c].get('final_price'))
