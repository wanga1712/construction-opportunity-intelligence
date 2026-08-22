#!/usr/bin/env python3
"""Read-only production lifecycle annotation-state audit."""
import json, os, sys
from pathlib import Path
root = Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit")); os.chdir(root); sys.path[:0] = [str(root), "/opt/pythonProject89"]
from dotenv import load_dotenv
load_dotenv(root / ".env", override=True)
from src.services.db_bootstrap import connect_databases
from src.ui.components.analytics_v2 import tabs
from annotation_state_service import load_current_annotation_states, annotation_state_counts

_, _, crm_db, _ = connect_databases()
out = {}
for label, loader in (("TORGI", tabs._load_torgi), ("COMMISSION", tabs._load_komissia), ("AWARDED", tabs._load_razygranye)):
    cards = loader(); states = load_current_annotation_states([row["id"] for row in cards], crm_db)
    counts = annotation_state_counts(states)
    examples = {key: [pid for pid, value in states.items() if value["annotation_state"] == key][:5] for key in ("UNANNOTATED", "ANNOTATED", "NOT_INTERESTING")}
    out[label] = {"counts": counts, "examples": examples}
print(json.dumps(out, ensure_ascii=False, default=str, indent=2))
