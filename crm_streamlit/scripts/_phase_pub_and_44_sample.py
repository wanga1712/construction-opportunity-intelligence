#!/usr/bin/env python3
from pathlib import Path
import json, sys
sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv
load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
from src.services.db_bootstrap import connect_databases
from src.services.annotation_queue_service import batch_publication_visibility

_, _, crm, _ = connect_databases()
print(json.dumps({
    "pub_17758": batch_publication_visibility(crm, [17758]),
    "sample_44": crm.execute_query(
        """
        SELECT id, contract_number, left(tender_link, 140) AS link
        FROM crm_procurements
        WHERE source_table ILIKE %s
          AND crm_stage = 'torgi'
          AND award_status = 'submission_open'
          AND end_date >= CURRENT_DATE
        LIMIT 5
        """,
        ("%44%",),
    ),
}, ensure_ascii=False, indent=2, default=str))
