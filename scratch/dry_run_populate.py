#!/usr/bin/env python3
import sys
from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer

def run_dry():
    print("Initializing Queue Producer...")
    producer = CommercialRoutingV3QueueProducer()
    print("Running populate_all_eligible in dry_run mode...")
    res = producer.populate_all_eligible(dry_run=True)
    print("Results:")
    for k, v in res.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    run_dry()
