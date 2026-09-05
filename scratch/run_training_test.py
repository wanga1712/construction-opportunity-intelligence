import os
import sys
import shutil
import json
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')

# Setup /tmp/dev_repo/src/learning
dev_src = '/tmp/dev_repo/src'
os.makedirs(f'{dev_src}/learning', exist_ok=True)
if os.path.exists('/tmp/learning_pkg'):
    for item in os.listdir('/tmp/learning_pkg'):
        src_item = f'/tmp/learning_pkg/{item}'
        dst_item = f'{dev_src}/learning/{item}'
        if os.path.isdir(src_item):
            if os.path.exists(dst_item):
                shutil.rmtree(dst_item)
            shutil.copytree(src_item, dst_item)
        else:
            shutil.copy2(src_item, dst_item)

sys.path.insert(0, '/opt/CRM_Streamlit')
import src
src.__path__.append(dev_src)

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
)
from src.learning.okpd_prior.train import train_and_evaluate_okpd_prior

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

print("Starting OKPD Prior Training & Evaluation...")
report = train_and_evaluate_okpd_prior(
    doc_conn,
    crm_conn,
    snapshot_dir="/tmp/okpd_prior_snapshots",
    model_dir="/tmp/okpd_prior_models",
)

print("\n" + "=" * 80)
print("TRAINING & EVALUATION COMPLETE")
print("=" * 80)
print(json.dumps(report, indent=2, ensure_ascii=False))
