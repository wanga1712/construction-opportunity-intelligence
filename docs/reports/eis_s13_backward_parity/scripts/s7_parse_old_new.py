"""
Run the old and new parsers' record extraction on one XML file
to see what contract_number and final_price they parse.
"""
import sys, json, importlib.util

XML = "/tmp/eis_s13_parity/rgk/contract_2770780719026000028_0_019FACC632FC794F82098EE37699DED9.xml"

# Load OLD serial parser
OLD = "/tmp/eis_s13_parity_old"
sys.path.insert(0, OLD)
# We just need the parse function, not DB
import importlib
old_parser_spec = importlib.util.spec_from_file_location(
    "old_rgk_record",
    f"{OLD}/parsing_xml/rgk_record.py"
)
old_mod = importlib.util.module_from_spec(old_parser_spec)
old_parser_spec.loader.exec_module(old_mod)

# Read tags config from old tree
import os
os.chdir(OLD)
from secondary_functions import load_config
tags = json.loads(open(load_config()["tags"]).read())

old_record, _ = old_mod.parse_rgk_file(XML, tags)
print("OLD contract_number:", getattr(old_record, 'contract_number', None))
print("OLD final_price:", getattr(old_record, 'final_price', None))
print("OLD regNum:", getattr(old_record, 'regNum', None) if hasattr(old_record, 'regNum') else 'N/A')
