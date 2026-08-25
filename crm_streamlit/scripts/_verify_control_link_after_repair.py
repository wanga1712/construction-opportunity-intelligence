#!/usr/bin/env python3
from pathlib import Path
import json, sys
sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv
load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
from src.services.db_bootstrap import connect_databases
from src.services.procurement_identity import resolve_procurement_link

_, _, crm, _ = connect_databases()
row = crm.execute_query(
    "SELECT id, contract_number, tender_link, source_table FROM crm_procurements WHERE id=17758"
)[0]
view = resolve_procurement_link(
    source_table=row["source_table"],
    contract_number=row["contract_number"],
    tender_link=row["tender_link"],
)
stats = crm.execute_query(
    """
    SELECT
      count(*) FILTER (WHERE tender_link ILIKE '%%lk.zakupki.gov.ru%%') AS private_lk,
      count(*) FILTER (WHERE tender_link ILIKE '%%notice223/common-info.html?regNumber=%%') AS public_epz
    FROM crm_procurements
    WHERE source_table ILIKE '%%223%%'
    """
)
print(json.dumps({"control": row, "view": view.__dict__, "stats_223": stats[0]}, ensure_ascii=False, indent=2, default=str))
