import json
import os
import sys

from src.learning.okpd_prior.dataset import (
    ProcurementDatasetRow,
    resolve_research_outcome,
    create_dataset_snapshot,
    split_dataset,
)
from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.learning.okpd_prior.train import train_and_evaluate_okpd_prior

# Read extracted rows
with open("scratch/extracted_procurement_rows.json", "r", encoding="utf-8") as f:
    raw_rows = json.load(f)

# Convert to ProcurementDatasetRow
dataset_rows = []
seen_pids = set()
for r in raw_rows:
    pid = r["procurement_id"]
    if pid in seen_pids:
        continue
    seen_pids.add(pid)

    raw_okpd = r["okpd_code"]
    hierarchy = parse_okpd_hierarchy(raw_okpd)
    outcome, research_hit = resolve_research_outcome(
        research_complete=(r["status"] == "COMPLETED"),
        trusted_confirmed_count=r["v4_confirmed"],
        semantic_unknown_count=r["v4_unknown"],
        pending_validation_count=r["pending_val"],
        technical_gap_count=0,
    )
    dataset_rows.append(ProcurementDatasetRow(
        procurement_id=pid,
        research_completed_at=r["completed_at"],
        okpd_code_raw=raw_okpd,
        okpd_root=hierarchy.okpd_root,
        okpd_level2=hierarchy.okpd_level2,
        okpd_level3=hierarchy.okpd_level3,
        okpd_full=hierarchy.okpd_full,
        outcome=outcome,
        research_hit=research_hit,
        trusted_confirmed_count=r["v4_confirmed"],
        rejected_count=r["v4_rejected"],
        unknown_count=r["v4_unknown"],
        pending_validation_count=r["pending_val"],
        research_document_count=r["file_count"],
    ))

print(f"Total dataset rows: {len(dataset_rows)}")
pos = sum(1 for r in dataset_rows if r.outcome == "POSITIVE")
safe_neg = sum(1 for r in dataset_rows if r.outcome == "SAFE_NEGATIVE")
unres = sum(1 for r in dataset_rows if r.outcome == "UNRESOLVED")
print(f"Positive: {pos}, Safe Negative: {safe_neg}, Unresolved: {unres}, Labeled: {pos + safe_neg}")

# Run training
import unittest.mock as mock

class MockDocConn:
    pass
class MockCrmConn:
    pass

with mock.patch("src.learning.okpd_prior.train.extract_procurement_dataset_from_db", return_value=dataset_rows):
    report = train_and_evaluate_okpd_prior(
        MockDocConn(),
        MockCrmConn(),
        snapshot_dir="data/okpd_prior_snapshots",
        model_dir="data/okpd_prior_models",
    )

print("\n" + "=" * 80)
print("TRAINING AND EVALUATION REPORT:")
print("=" * 80)
print(json.dumps(report, indent=2, ensure_ascii=False))
