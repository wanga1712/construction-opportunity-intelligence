"""CLI runner for OKPD Prior V1 Prospective Shadow Evaluation.

Usage:
    python scripts/run_okpd_prospective_evaluation.py [--input candidate_rows.json] [--output-dir data/okpd_prior_evaluation]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Ensure repository root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.learning.okpd_prior.dataset import ProcurementDatasetRow
from src.learning.okpd_prior.prospective_evaluation import run_prospective_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OKPD Prior V1 Prospective Shadow Evaluation")
    parser.add_argument("--input", type=str, default=None, help="Path to prospective candidates JSON")
    parser.add_argument("--output-dir", type=str, default="data/okpd_prior_evaluation", help="Output directory")
    args = parser.parse_args()

    candidates = None
    if args.input and os.path.isfile(args.input):
        with open(args.input, "r", encoding="utf-8") as f:
            raw = json.load(f)
        candidates = [
            ProcurementDatasetRow(
                procurement_id=r["procurement_id"],
                research_completed_at=r.get("research_completed_at"),
                okpd_code_raw=r.get("okpd_code_raw"),
                okpd_root=r["okpd_root"],
                okpd_level2=r["okpd_level2"],
                okpd_level3=r["okpd_level3"],
                okpd_full=r["okpd_full"],
                outcome=r["outcome"],
                research_hit=r.get("research_hit"),
                trusted_confirmed_count=r.get("trusted_confirmed_count", 0),
                rejected_count=r.get("rejected_count", 0),
                unknown_count=r.get("unknown_count", 0),
                pending_validation_count=r.get("pending_validation_count", 0),
                research_document_count=r.get("research_document_count", 0),
            )
            for r in raw
        ]

    report = run_prospective_evaluation(candidate_rows=candidates, output_dir=args.output_dir)

    print("\n" + "=" * 80)
    print("OKPD PRIOR V1: PROSPECTIVE SHADOW EVALUATION REPORT")
    print("=" * 80)
    counts = report["corpus_counts"]
    print(f"HISTORICAL_LABELED:            {counts['historical_labeled']}")
    print(f"PROSPECTIVE_TOTAL_SEEN:        {counts['prospective_total_seen']}")
    print(f"PROSPECTIVE_LABELED:           {counts['prospective_labeled']}")
    print(f"PROSPECTIVE_POSITIVES:         {counts['prospective_positives']}")
    print(f"PROSPECTIVE_SAFE_NEGATIVES:    {counts['prospective_safe_negatives']}")
    print(f"PROSPECTIVE_UNRESOLVED:        {counts['prospective_unresolved']}")
    print(f"UNSEEN_OKPD_CODES:             {counts['unseen_okpd_codes']}")
    print("-" * 80)
    gates = report["evaluation_gates"]
    print(f"CORPUS_GATE:                   {gates['corpus_gate']}")
    print(f"EVALUATION_STATUS:             {gates['evaluation_status']}")
    print(f"PROMOTION_REVIEW_ELIGIBLE:     {gates['promotion_review_eligible']}")
    print(f"PRODUCTION_PRIORITY_PROMOTION: {gates['production_priority_promotion']}")
    print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
