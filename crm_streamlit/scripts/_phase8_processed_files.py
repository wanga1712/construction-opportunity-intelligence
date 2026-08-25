#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
from src.services.db_bootstrap import connect_databases

_, tender, crm, _ = connect_databases()
out = {}
out["processed"] = tender.execute_query(
    """
    SELECT id, tender_id, registry_type, file_path, file_name, processing_status, processed_at
    FROM processed_files
    WHERE tender_id = %s
       OR file_name ILIKE %s
       OR file_path ILIKE %s
    ORDER BY id DESC
    LIMIT 20
    """,
    (151355, "%32615833902%", "%32615833902%"),
)
out["file_names"] = tender.execute_query(
    """
    SELECT id, file_name, processed_at
    FROM file_names_xml
    WHERE file_name ILIKE %s
    ORDER BY id DESC
    LIMIT 20
    """,
    ("%32615833902%",),
)
print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
