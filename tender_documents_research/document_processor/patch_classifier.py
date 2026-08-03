#!/usr/bin/env python3
"""Patch matcher.py and task_pipeline.py to add contract pre-classification."""
import sys
import shutil
from datetime import datetime

TS = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE = "/opt/tender_documents_research/document_processor"

# ── 1. matcher.py ────────────────────────────────────────────────────────────
MATCHER_PATH = f"{BASE}/matcher.py"

with open(MATCHER_PATH) as f:
    matcher = f.read()

shutil.copy2(MATCHER_PATH, f"{MATCHER_PATH}.bak_{TS}")

# Change process_text signature to accept category_scores
OLD_SIG = "    def process_text(self, text: str, line_meta: Optional[Dict[int, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:"
NEW_SIG = "    def process_text(self, text: str, line_meta: Optional[Dict[int, Dict[str, Any]]] = None, category_scores: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:"
if OLD_SIG not in matcher:
    print("MATCHER PATCH FAILED: process_text signature not found", file=sys.stderr)
    sys.exit(1)
matcher = matcher.replace(OLD_SIG, NEW_SIG, 1)

# Add category filter inside the keyword loop, right after keyword_meta is fetched
OLD_LOOP = """        for keyword in self.keywords:
            keyword_meta = self.keyword_meta.get(keyword) or {}
            keyword_negative_phrases = keyword_meta.get("negative_phrases") or []"""
NEW_LOOP = """        import os as _os
        _skip_threshold = float(_os.getenv("CLASSIFIER_SKIP_THRESHOLD", "2"))
        for keyword in self.keywords:
            keyword_meta = self.keyword_meta.get(keyword) or {}
            keyword_negative_phrases = keyword_meta.get("negative_phrases") or []
            # Category pre-filter: skip keywords from categories with low LLM score
            if category_scores:
                _codes = keyword_meta.get("category_codes") or []
                if _codes:
                    _cat_score = category_scores.get(_codes[0], 10.0)
                    if _cat_score < _skip_threshold:
                        continue"""
if OLD_LOOP not in matcher:
    print("MATCHER PATCH FAILED: keyword loop head not found", file=sys.stderr)
    sys.exit(1)
matcher = matcher.replace(OLD_LOOP, NEW_LOOP, 1)

with open(MATCHER_PATH, "w") as f:
    f.write(matcher)
print(f"OK matcher.py patched (backup: matcher.py.bak_{TS})")

# ── 2. task_pipeline.py ──────────────────────────────────────────────────────
PIPELINE_PATH = f"{BASE}/task_pipeline.py"

with open(PIPELINE_PATH) as f:
    pipeline = f.read()

shutil.copy2(PIPELINE_PATH, f"{PIPELINE_PATH}.bak_{TS}")

# Add import at top (after existing imports)
OLD_IMPORT = "from document_processor.registry_contract_locator import RegistryContractLocator"
NEW_IMPORT = (
    "from document_processor.registry_contract_locator import RegistryContractLocator\n"
    "from document_processor.contract_classifier import ContractClassifier"
)
if OLD_IMPORT not in pipeline:
    print("PIPELINE PATCH FAILED: import anchor not found", file=sys.stderr)
    sys.exit(1)
pipeline = pipeline.replace(OLD_IMPORT, NEW_IMPORT, 1)

# Add classifier init in __init__
OLD_LOCATOR = "        self.contract_locator = RegistryContractLocator(db, \"tender_monitor\", logger)"
NEW_LOCATOR = (
    "        self.contract_locator = RegistryContractLocator(db, \"tender_monitor\", logger)\n"
    "        self.classifier = ContractClassifier(db, logger)"
)
if OLD_LOCATOR not in pipeline:
    print("PIPELINE PATCH FAILED: contract_locator init not found", file=sys.stderr)
    sys.exit(1)
pipeline = pipeline.replace(OLD_LOCATOR, NEW_LOCATOR, 1)

# Add category_scores computation at start of process_task_with_files,
# right after the log line.
OLD_PROC_START = '        self.logger.info(f"[{task_id}] Получено файлов: {len(files)}")'
NEW_PROC_START = (
    '        self.logger.info(f"[{task_id}] Получено файлов: {len(files)}")\n'
    "        try:\n"
    "            category_scores = self.classifier.classify(contract_reg_number, table_source)\n"
    "        except Exception as _clf_exc:\n"
    "            self.logger.warning(f\"[{task_id}] classifier error: {_clf_exc}\")\n"
    "            category_scores = {}"
)
if OLD_PROC_START not in pipeline:
    print("PIPELINE PATCH FAILED: process_task_with_files log line not found", file=sys.stderr)
    sys.exit(1)
pipeline = pipeline.replace(OLD_PROC_START, NEW_PROC_START, 1)

# Pass category_scores to all process_text calls
pipeline = pipeline.replace(
    "matches = self.matcher.process_text(\n                                    text, line_meta=line_meta\n                                )",
    "matches = self.matcher.process_text(\n                                    text, line_meta=line_meta, category_scores=category_scores\n                                )",
)
pipeline = pipeline.replace(
    "matches = self.matcher.process_text(text, line_meta=line_meta)",
    "matches = self.matcher.process_text(text, line_meta=line_meta, category_scores=category_scores)",
)

with open(PIPELINE_PATH, "w") as f:
    f.write(pipeline)
print(f"OK task_pipeline.py patched (backup: task_pipeline.py.bak_{TS})")
print("All patches applied successfully")
