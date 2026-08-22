#!/usr/bin/env python3
"""Read-only factual procurement/contract link audit for control corpus."""
import json, os, sys
from pathlib import Path
from urllib.parse import urlparse
root=Path(os.environ.get("CRM_APP_ROOT","/opt/CRM_Streamlit")); os.chdir(root); sys.path[:0]=[str(root),os.environ.get("CRM_SOURCE_ROOT","/opt/pythonProject89")]
from dotenv import load_dotenv
load_dotenv(root/".env",override=True)
from src.services.annotation_card_view import load_annotation_card_view
from src.services.annotation_queue_service import fetch_procurement_header
from src.services.db_bootstrap import connect_databases
_,_,db,_=connect_databases(); out=[]
for pid in (1013,8021,17390,20254,20256):
    header=fetch_procurement_header(db,pid); view=load_annotation_card_view(pid,header,db); facts=view["facts"]
    tender=facts.get("procurement_url"); contract=facts.get("contract_url")
    label="Закупка на ЕИС" if tender and "zakupki.gov.ru" in (urlparse(tender).hostname or "").lower() else "Открыть закупку"
    out.append({"crm_id":pid,"source_table":header.get("source_table"),"tender_link":tender,"procurement_link_rendered":bool(tender),"procurement_link_label":label if tender else None,"contract_link":contract,"contract_link_rendered":bool(contract)})
print(json.dumps(out,ensure_ascii=False,default=str,indent=2))
