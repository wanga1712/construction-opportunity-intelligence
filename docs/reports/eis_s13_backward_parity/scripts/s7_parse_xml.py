import subprocess, re

fname = "/tmp/eis_s13_parity/rgk/contract_2770780719026000028_0_019FACC632FC794F82098EE37699DED9.xml"

with open(fname, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find all contract numbers
nums = re.findall(r'<(?:number|regNum)>(\d+)</(?:number|regNum)>', content)
print("contract numbers found:", nums[:20])

# Find all price-like values
prices = re.findall(r'<(?:[a-zA-Z]*[Pp]rice|contractSum|sum)[^>]*>([0-9.]+)</[^>]+>', content)
print("prices found:", prices[:20])
