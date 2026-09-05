import sys
sys.path.insert(0, '/opt/CRM_Streamlit')

import os
import psycopg2
import psycopg2.extras
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('populate')

crm_dsn = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "crm",
    "user": "crm_app",
    "password": "X17B3n5hbANQSRt6i7WIyy0lJudX",
}

doc_dsn = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "document_intelligence",
    "user": "crm_app",
    "password": "X17B3n5hbANQSRt6i7WIyy0lJudX",
}

from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer

producer = CommercialRoutingV3QueueProducer.__new__(CommercialRoutingV3QueueProducer)
producer.enabled = True
producer._crm_dsn = crm_dsn
producer._doc_dsn = doc_dsn

logger.info("Starting populate_all_eligible(dry_run=False)...")
logger.info("AI_QUEUE_ADMISSION_GATE=NO — queuing all eligible procurements with links")

result = producer.populate_all_eligible(
    dry_run=False,
    batch_size=5000,
    max_total=0,  # no limit
)

import json
logger.info(f"POPULATE_RESULT: {json.dumps(result, default=str)}")
print("DONE")
print(json.dumps(result, indent=2, default=str))
