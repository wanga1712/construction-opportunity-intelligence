import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.bootstrap import setup_source_path

setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.object_ai_classification_store import ensure_schema

_, _, crm_db, warn = connect_databases()
print("warn", warn)
ensure_schema(crm_db)
rows = crm_db.execute_query("SELECT count(*) AS cnt FROM crm_object_ai_classifications")
print("crm_object_ai_classifications", rows[0]["cnt"] if rows else 0)
