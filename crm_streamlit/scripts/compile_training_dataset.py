"""Compile training dataset from completed canary traces and expert annotations."""
import os
import sys
import json
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.sparse_dataset_compiler import SparseDatasetCompiler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("compile_training_dataset")

class CRMDBWrapper:
    def __init__(self, db_mgr):
        self.db_mgr = db_mgr
    def execute_query(self, sql, params=None):
        return self.db_mgr.execute_query(sql, params)
    def execute_update(self, sql, params=None):
        return self.db_mgr.execute_update(sql, params)
    def execute_scalar(self, sql, params=None):
        rows = self.db_mgr.execute_query(sql, params)
        if rows:
            row = rows[0]
            return row[0] if isinstance(row, (tuple, list)) else next(iter(row.values()))
        return None

def main():
    logger.info("Connecting to databases...")
    _, _, crm_db_orig, _ = connect_databases()
    crm_db = CRMDBWrapper(crm_db_orig)
    
    compiler = SparseDatasetCompiler(crm_db)
    
    # Select all unique procurement IDs that have completed traces
    rows = crm_db.execute_query(
        "SELECT DISTINCT procurement_id FROM crm_v3_autonomous_analysis_traces"
    )
    pids = [r["procurement_id"] if isinstance(r, dict) else r[0] for r in rows]
    logger.info(f"Found {len(pids)} procurements with learning loop traces.")
    
    dataset = []
    for pid in pids:
        try:
            entry = compiler.compile_target(pid)
            if entry:
                dataset.append(entry)
        except Exception as exc:
            logger.error(f"Error compiling target for procurement {pid}: {exc}")
            
    # Write dataset to JSON
    output_file = "/tmp/compiled_training_dataset.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Successfully compiled {len(dataset)} training entries to {output_file}")

if __name__ == "__main__":
    main()
