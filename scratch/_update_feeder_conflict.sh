#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_feeder = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/factual_feeder.py"

with open(path_feeder, "r", encoding="utf-8") as f:
    code = f.read()

target = '''                # Enqueue factual task
                cur.execute(
                    """
                    INSERT INTO document_processing_queue (
                        procurement_id, source_table, source_id, contract_number,
                        research_action, queue_lane, priority_score, status,
                        pipeline_generation, created_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        'FACTUAL_FEEDER_ADMITTED', 'open_active', 50, 'PENDING',
                        %s, NOW()
                    )
                    RETURNING id
                    """,
                    (
                        procurement_id,
                        source_table,
                        source_id,
                        contract_number,
                        PIPELINE_GENERATION,
                    ),
                )
                new_id = cur.fetchone()["id"]
                conn.commit()'''

replacement = '''                # Enqueue factual task with ON CONFLICT clause
                cur.execute(
                    """
                    INSERT INTO document_processing_queue (
                        procurement_id, source_table, source_id, contract_number,
                        research_action, queue_lane, priority_score, status,
                        pipeline_generation, created_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        'FACTUAL_FEEDER_ADMITTED', 'open_active', 50, 'PENDING',
                        %s, NOW()
                    )
                    ON CONFLICT (procurement_id, pipeline_generation) DO NOTHING
                    RETURNING id
                    """,
                    (
                        procurement_id,
                        source_table,
                        source_id,
                        contract_number,
                        PIPELINE_GENERATION,
                    ),
                )
                res = cur.fetchone()
                new_id = res["id"] if res else (row["id"] if row else None)
                conn.commit()'''

assert target in code, "INSERT query target not found in factual_feeder.py"

code = code.replace(target, replacement)

with open(path_feeder, "w", encoding="utf-8") as f:
    f.write(code)

print("UPDATED factual_feeder.py WITH ON CONFLICT DO NOTHING CLAUSE!")
PYEOF
