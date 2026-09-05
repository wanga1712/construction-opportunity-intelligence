import sys, subprocess, os

# Restore autonomous_learning_loop.py and autonomous_worker.py from parent 3cbab40e5d03f9c4db06ee28faee52bab479565d
cmd = "cd /opt/CRM_Streamlit_rescue; git checkout 3cbab40e5d03f9c4db06ee28faee52bab479565d -- src/services/commercial_routing_v3/autonomous_learning_loop.py src/services/commercial_routing_v3/autonomous_worker.py"
subprocess.run(cmd, shell=True, check=True)
print("RESTORED FROM 3cbab40 COMPLETE")

# Patch autonomous_learning_loop.py cleanly
loop_path = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"
with open(loop_path, "r", encoding="utf-8") as f:
    lp = f.read()

target = "        docs, doc_set_hash = self.fetch_document_research_summary(procurement_id)"
replacement = '''        registry = self.load_active_categories()
        reg_hash = self.compute_registry_hash(registry)
        model_version = "qwen2.5:7b"
        docs, doc_set_hash = self.fetch_document_research_summary(procurement_id)'''

if target in lp:
    lp = lp.replace(target, replacement, 1)
    with open(loop_path, "w", encoding="utf-8") as f:
        f.write(lp)
    print("LEARNING LOOP PATCHED")

# Patch autonomous_worker.py
worker_path = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_worker.py"
with open(worker_path, "r", encoding="utf-8") as f:
    wk = f.read()

old_q = "FROM document_processing_queue\n                            WHERE status IN ('COMPLETED', 'FAILED', 'NO_LINKS')"
new_q = "FROM document_processing_queue q\n                            WHERE q.status IN ('COMPLETED', 'FAILED', 'NO_LINKS')"

if old_q in wk:
    wk = wk.replace(old_q, new_q)

old_order = "ORDER BY id DESC"
new_order = '''ORDER BY 
                CASE q.queue_lane 
                    WHEN 'crm_active_hot' THEN 1 
                    WHEN 'open_active' THEN 2 
                    WHEN 'awarded_recent' THEN 3 
                    WHEN 'retry' THEN 4 
                    WHEN 'historical_awarded' THEN 5 
                    ELSE 6 
                END ASC,
                q.priority_score DESC,
                q.id DESC'''

if "FROM document_processing_queue q" in wk and old_order in wk:
    wk = wk.replace(old_order, new_order, 2)

with open(worker_path, "w", encoding="utf-8") as f:
    f.write(wk)
print("AUTONOMOUS WORKER PATCHED")
