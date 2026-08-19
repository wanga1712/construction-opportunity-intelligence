"""
Test old xml_parser.py on the file that references 0373200081226000248.
"""
import sys, json, os, importlib.util

XML = "/tmp/eis_s13_parity/rgk/contract_2770780719026000028_0_019FACC632FC794F82098EE37699DED9.xml"
OLD = "/tmp/eis_s13_parity_old"
sys.path.insert(0, OLD)
os.chdir(OLD)
from secondary_functions import load_config
cfg = load_config()
tags_file = cfg.get("main", "tags", fallback=None) or cfg.get("tags", fallback=None) or cfg["tags"]
print("tags_file:", tags_file)
tags = json.loads(open(tags_file).read())

spec = importlib.util.spec_from_file_location("old_xml_parser", f"{OLD}/parsing_xml/xml_parser.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Try to call whatever parse function exists
print("Functions:", [x for x in dir(mod) if 'parse' in x.lower() or 'contract' in x.lower()])
