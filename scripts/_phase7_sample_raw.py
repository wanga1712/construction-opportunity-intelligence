#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)
from src.services.db_bootstrap import connect_databases

_, _, crm, _ = connect_databases()
r = crm.execute_query(
    """
    SELECT id, length(raw_model_text) AS n,
           left(raw_model_text, 500) AS head,
           right(raw_model_text, 500) AS tail,
           ollama_metadata->>'eval_count' AS ev,
           ollama_metadata->>'num_predict' AS np
    FROM crm_v3_model_inference_runs WHERE id = 7
    """
)
print(json.dumps([dict(x) for x in r], ensure_ascii=False, indent=2, default=str))
