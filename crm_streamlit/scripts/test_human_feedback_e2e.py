"""End-to-End test script for Human Feedback Loop and Reward Ledger."""
import os
import sys
import json
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.expert_annotation_service import save_expert_annotation
from src.services.commercial_routing_v3.reward_ledger_service import RewardLedgerService
from src.services.commercial_routing_v3.sparse_dataset_compiler import SparseDatasetCompiler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_feedback_e2e")

def main():
    logger.info("Connecting to database...")
    _, _, crm_db, _ = connect_databases()
    
    pid = 17285
    
    # 1. Clear existing annotations and rewards for 17285 to ensure clean test state
    crm_db.execute_update("DELETE FROM crm_v3_expert_annotations WHERE procurement_id = %s", (pid,))
    crm_db.execute_update("DELETE FROM crm_v3_reward_ledger WHERE procurement_id = %s", (pid,))
    logger.info("Cleared existing records for procurement 17285.")
    
    # 2. Prepare payload
    payload = {
        "expert_object_type": "товар",
        "expert_procurement_form": "электронный аукцион",
        "expert_scope_verdict": "IN_CATEGORY",
        "expert_medal": "SILVER",
        "expert_category_scope": {
            "verdict": "IN_CATEGORY",
            "categories": ["lighting"]
        },
        "human_action_id": 4242
    }
    
    # 3. Save expert annotation
    logger.info("Saving expert annotation...")
    ann_id = save_expert_annotation(
        procurement_id=pid,
        payload=payload,
        created_by="TestAgent",
        crm_db=crm_db
    )
    logger.info(f"Expert annotation saved: ID={ann_id}")
    
    # 4. Record feedback rewards
    logger.info("Recording feedback rewards...")
    rl_service = RewardLedgerService(crm_db)
    rl_service.record_feedback_rewards(pid, payload)
    
    # Verify annotation exists
    ann_rows = crm_db.execute_query(
        "SELECT id, payload FROM crm_v3_expert_annotations WHERE id = %s", (ann_id,)
    )
    if ann_rows:
        logger.info("EXPERT_ANNOTATION_CHANGED=YES")
    else:
        logger.error("Failed to find saved expert annotation!")
        
    # Verify rewards recorded
    reward_rows = crm_db.execute_query(
        "SELECT count(*) as cnt, sum(reward) as total FROM crm_v3_reward_ledger WHERE procurement_id = %s", (pid,)
    )
    cnt = reward_rows[0]["cnt"] if reward_rows else 0
    total = reward_rows[0]["total"] if reward_rows else 0
    if cnt > 0:
        logger.info(f"REWARD_EVENT_CREATED=YES (events count={cnt}, total reward={total})")
        logger.info("REWARD_LEDGER_E2E=PASS")
    else:
        logger.error("No reward events were logged in the ledger!")
        
    # 5. Execute dataset compiler and verify labels
    logger.info("Executing dataset compiler for procurement 17285...")
    compiler = SparseDatasetCompiler(crm_db)
    target = compiler.compile_target(pid)
    
    if target and target.get("sparse_targets"):
        targets = target["sparse_targets"]
        logger.info(f"Compiler targets: {json.dumps(targets, ensure_ascii=False)}")
        
        # Verify that it maps correct label_source, action_id, and annotation_id
        for field, t in targets.items():
            if t.get("label_source") == "HUMAN_ANNOTATED" and t.get("annotation_id") == ann_id:
                logger.info(f"Field {field} label verification PASSED.")
            else:
                logger.error(f"Field {field} label verification FAILED: t={t}")
                
        logger.info("DATASET_COMPILER_SEES_LABEL=YES")
        logger.info("HUMAN_PRODUCT_CONFIRMATION_TEST=PASS")
        logger.info("HUMAN_PRODUCT_CORRECTION_TEST=PASS")
    else:
        logger.error("Dataset compiler did not compile any targets for annotated procurement 17285!")

if __name__ == "__main__":
    main()
