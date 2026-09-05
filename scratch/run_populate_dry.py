import sys
sys.path.insert(0, '/opt/CRM_Streamlit')

import os
import psycopg2

# CRM DB DSN
crm_dsn = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "crm",
    "user": "crm_app",
    "password": "X17B3n5hbANQSRt6i7WIyy0lJudX",
}

# Document intelligence DB DSN
doc_dsn = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "document_intelligence",
    "user": "crm_app",
    "password": "X17B3n5hbANQSRt6i7WIyy0lJudX",
}

from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer

# Build the producer manually (bypassing the full init which requires DB env vars)
producer = CommercialRoutingV3QueueProducer.__new__(CommercialRoutingV3QueueProducer)
producer.enabled = True
producer._crm_dsn = crm_dsn
producer._doc_dsn = doc_dsn

print("=== DRY RUN first ===")
dry_result = producer.populate_all_eligible(dry_run=True, batch_size=5000, max_total=5000)
print(f"DRY RUN result: {dry_result}")

import json
print(json.dumps(dry_result, indent=2, default=str))
