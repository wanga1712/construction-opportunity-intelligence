import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()
from src.services.parking_db import ParkingDatabase

kn = sys.argv[1] if len(sys.argv) > 1 else "77:06:0008011:4177"
db = ParkingDatabase()
db.connect()
r = db.query_one(
    """
    SELECT cm.status, cm.error_text, cm.mk_address, cm.search_query,
           cm.raw_house_json, cm.raw_management_json, cm.enriched_at,
           mc.name AS uk_name, mc.ogrn
    FROM cadastral_object_management cm
    JOIN cadastral_object co ON co.id = cm.cadastral_object_id
    LEFT JOIN management_company mc ON mc.id = cm.management_company_id
    WHERE co.cadastral_number = %s
    """,
    (kn,),
)
print("status:", r.get("status"))
print("error:", r.get("error_text"))
print("uk_name:", r.get("uk_name"), "ogrn:", r.get("ogrn"))
rm = r.get("raw_management_json")
if rm:
    print("raw_management:", json.dumps(rm, ensure_ascii=False, indent=2)[:3000])
