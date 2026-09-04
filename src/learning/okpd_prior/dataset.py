"""Dataset extraction, labeling, and snapshot generation for OKPD Prior Learning.

Contract:
- One row = One procurement (unique procurement_id).
- Labels:
  - POSITIVE: research completed AND >=1 trusted V4 CONFIRMED candidate (research_hit=1).
  - SAFE_NEGATIVE: research completed AND 0 CONFIRMED AND 0 UNKNOWN AND 0 pending (research_hit=0).
  - UNRESOLVED: excluded from training (research incomplete, pending validations, semantic unknowns).
- Model features: ONLY okpd_root, okpd_level2, okpd_level3, okpd_full.
- Diagnostic fields are never passed as features to ML models.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import psycopg2.extras

from src.learning.okpd_prior.hierarchy import (
    OKPDHierarchy,
    UNKNOWN_OKPD,
    parse_okpd_hierarchy,
)

PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"
VALIDATOR_NAME = "context_validator"
VALIDATOR_VERSION = "v4"
VALIDATION_METHOD = "QWEN_CONTEXT_V4"

OUTCOME_POSITIVE = "POSITIVE"
OUTCOME_SAFE_NEGATIVE = "SAFE_NEGATIVE"
OUTCOME_UNRESOLVED = "UNRESOLVED"


@dataclass
class ProcurementDatasetRow:
    """Represents a single procurement row in the research dataset."""
    procurement_id: int
    research_completed_at: Optional[str]
    okpd_code_raw: Optional[str]
    okpd_root: str
    okpd_level2: str
    okpd_level3: str
    okpd_full: str
    outcome: str
    research_hit: Optional[int]
    # Diagnostic counts (must NOT be used as model features)
    trusted_confirmed_count: int
    rejected_count: int
    unknown_count: int
    pending_validation_count: int
    research_document_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_feature_dict(self) -> Dict[str, str]:
        """Returns ONLY pre-research hierarchical OKPD features."""
        return {
            "okpd_root": self.okpd_root,
            "okpd_level2": self.okpd_level2,
            "okpd_level3": self.okpd_level3,
            "okpd_full": self.okpd_full,
        }


def resolve_research_outcome(
    research_complete: bool,
    trusted_confirmed_count: int,
    semantic_unknown_count: int,
    pending_validation_count: int,
    technical_gap_count: int = 0,
) -> Tuple[str, Optional[int]]:
    """Pure helper resolving procurement outcome and binary target.

    Contract:
    - confirmed >= 1 -> POSITIVE (research_hit=1)
    - complete + 0 confirmed + 0 unknown + 0 pending + 0 technical -> SAFE_NEGATIVE (research_hit=0)
    - unknown > 0 (without confirmed) -> UNRESOLVED (research_hit=None)
    - pending > 0 (without confirmed) -> UNRESOLVED (research_hit=None)
    - technical gap > 0 (without confirmed) -> UNRESOLVED (research_hit=None)
    - research incomplete (without confirmed) -> UNRESOLVED (research_hit=None)

    Returns:
        (outcome, research_hit)
    """
    if trusted_confirmed_count >= 1:
        return OUTCOME_POSITIVE, 1

    if not research_complete:
        return OUTCOME_UNRESOLVED, None

    if technical_gap_count > 0:
        return OUTCOME_UNRESOLVED, None

    if semantic_unknown_count == 0 and pending_validation_count == 0:
        return OUTCOME_SAFE_NEGATIVE, 0

    return OUTCOME_UNRESOLVED, None


def extract_procurement_dataset_from_db(
    doc_conn,
    crm_conn,
    pipeline_generation: str = PIPELINE_GENERATION,
) -> List[ProcurementDatasetRow]:
    """Extracts procurement rows from document and CRM databases with strict labeling.

    Args:
        doc_conn: psycopg2 connection to document_intelligence database.
        crm_conn: psycopg2 connection to crm database.
        pipeline_generation: generation identifier string.

    Returns:
        List of ProcurementDatasetRow for all completed queue tasks.
    """
    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as doc_cur:
        doc_cur.execute("""
            WITH detail_counts AS (
                SELECT 
                    procurement_id,
                    count(*) as total_details,
                    count(*) FILTER (
                        WHERE validation_status = 'CONFIRMED' 
                          AND validator_name = %s 
                          AND lower(validator_version) = %s 
                          AND upper(validation_method) = %s
                    ) as v4_confirmed,
                    count(*) FILTER (
                        WHERE validation_status = 'REJECTED' 
                          AND validator_name = %s 
                          AND lower(validator_version) = %s 
                          AND upper(validation_method) = %s
                    ) as v4_rejected,
                    count(*) FILTER (
                        WHERE validation_status = 'UNKNOWN' 
                          AND validator_name = %s 
                          AND lower(validator_version) = %s 
                          AND upper(validation_method) = %s
                    ) as v4_unknown,
                    count(*) FILTER (WHERE validated_at IS NULL) as pending_val
                FROM document_match_details
                WHERE pipeline_generation = %s
                GROUP BY procurement_id
            ),
            file_counts AS (
                SELECT procurement_id, count(*) as file_count
                FROM document_files
                WHERE pipeline_generation = %s
                GROUP BY procurement_id
            )
            SELECT 
                q.procurement_id, 
                q.status, 
                q.completed_at,
                COALESCE(fc.file_count, 0) as file_count,
                COALESCE(dc.total_details, 0) as total_details,
                COALESCE(dc.v4_confirmed, 0) as v4_confirmed,
                COALESCE(dc.v4_rejected, 0) as v4_rejected,
                COALESCE(dc.v4_unknown, 0) as v4_unknown,
                COALESCE(dc.pending_val, 0) as pending_val
            FROM document_processing_queue q
            LEFT JOIN detail_counts dc ON dc.procurement_id = q.procurement_id
            LEFT JOIN file_counts fc ON fc.procurement_id = q.procurement_id
            WHERE q.status = 'COMPLETED'
              AND q.pipeline_generation = %s
            ORDER BY q.completed_at ASC, q.procurement_id ASC
        """, (
            VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper(),
            VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper(),
            VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper(),
            pipeline_generation, pipeline_generation, pipeline_generation,
        ))
        queue_rows = doc_cur.fetchall()

    proc_ids = [r["procurement_id"] for r in queue_rows]
    crm_map: Dict[int, Dict[str, Any]] = {}
    if proc_ids:
        with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as crm_cur:
            crm_cur.execute(
                "SELECT id, okpd_code FROM crm_procurements WHERE id = ANY(%s)",
                (proc_ids,),
            )
            for r in crm_cur.fetchall():
                crm_map[r["id"]] = r

    rows: List[ProcurementDatasetRow] = []
    seen_procs = set()

    for q in queue_rows:
        pid = q["procurement_id"]
        if pid in seen_procs:
            continue
        seen_procs.add(pid)

        raw_okpd = crm_map.get(pid, {}).get("okpd_code")
        hierarchy = parse_okpd_hierarchy(raw_okpd)

        v4_confirmed = q["v4_confirmed"]
        v4_unknown = q["v4_unknown"]
        pending_val = q["pending_val"]
        v4_rejected = q["v4_rejected"]
        file_count = q["file_count"]

        # Label resolution contract via authoritative helper
        outcome, research_hit = resolve_research_outcome(
            research_complete=(q["status"] == "COMPLETED"),
            trusted_confirmed_count=v4_confirmed,
            semantic_unknown_count=v4_unknown,
            pending_validation_count=pending_val,
            technical_gap_count=0,
        )

        comp_at_str = q["completed_at"].isoformat() if q["completed_at"] else None

        row = ProcurementDatasetRow(
            procurement_id=pid,
            research_completed_at=comp_at_str,
            okpd_code_raw=raw_okpd,
            okpd_root=hierarchy.okpd_root,
            okpd_level2=hierarchy.okpd_level2,
            okpd_level3=hierarchy.okpd_level3,
            okpd_full=hierarchy.okpd_full,
            outcome=outcome,
            research_hit=research_hit,
            trusted_confirmed_count=v4_confirmed,
            rejected_count=v4_rejected,
            unknown_count=v4_unknown,
            pending_validation_count=pending_val,
            research_document_count=file_count,
        )
        rows.append(row)

    return rows


def split_dataset(
    rows: List[ProcurementDatasetRow],
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
) -> Tuple[List[ProcurementDatasetRow], List[ProcurementDatasetRow], List[ProcurementDatasetRow], bool]:
    """Splits labeled rows temporally (or deterministically by hash) into Train/Val/Holdout.

    Args:
        rows: Labeled rows (excluding UNRESOLVED).
        train_ratio: Proportion for training set (default 0.70).
        val_ratio: Proportion for validation set (default 0.15).

    Returns:
        (train_rows, val_rows, holdout_rows, temporal_split_available)
    """
    usable_rows = [r for r in rows if r.research_hit is not None]
    
    # Check if timestamps are present and distinct
    has_timestamps = all(r.research_completed_at is not None for r in usable_rows)
    distinct_timestamps = len({r.research_completed_at for r in usable_rows}) > 1

    if has_timestamps and distinct_timestamps:
        sorted_rows = sorted(usable_rows, key=lambda r: (r.research_completed_at or "", r.procurement_id))
        n = len(sorted_rows)
        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)
        train_rows = sorted_rows[:n_train]
        val_rows = sorted_rows[n_train:n_train + n_val]
        holdout_rows = sorted_rows[n_train + n_val:]
        return train_rows, val_rows, holdout_rows, True
    else:
        # Fallback to deterministic hash split
        def _hash_bucket(pid: int) -> float:
            h = hashlib.sha256(f"proc_{pid}".encode("utf-8")).hexdigest()
            return int(h[:8], 16) / 0xFFFFFFFF

        train_rows, val_rows, holdout_rows = [], [], []
        for r in usable_rows:
            bucket = _hash_bucket(r.procurement_id)
            if bucket < train_ratio:
                train_rows.append(r)
            elif bucket < train_ratio + val_ratio:
                val_rows.append(r)
            else:
                holdout_rows.append(r)
        return train_rows, val_rows, holdout_rows, False


def create_dataset_snapshot(
    rows: List[ProcurementDatasetRow],
    output_path: str,
) -> Dict[str, Any]:
    """Serializes dataset snapshot and computes reproducible manifest metadata.

    Args:
        rows: List of ProcurementDatasetRow.
        output_path: Filepath where JSON snapshot is saved.

    Returns:
        Manifest dictionary.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    data_payload = [r.to_dict() for r in rows]
    serialized = json.dumps(data_payload, ensure_ascii=False, indent=2, sort_keys=True)
    snapshot_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(serialized)

    pos_count = sum(1 for r in rows if r.outcome == OUTCOME_POSITIVE)
    safe_neg_count = sum(1 for r in rows if r.outcome == OUTCOME_SAFE_NEGATIVE)
    unresolved_count = sum(1 for r in rows if r.outcome == OUTCOME_UNRESOLVED)
    labeled_count = pos_count + safe_neg_count
    pos_rate = (pos_count / labeled_count) if labeled_count > 0 else 0.0

    manifest = {
        "snapshot_created_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_file": output_path,
        "snapshot_sha256": snapshot_sha256,
        "total_procurements": len(rows),
        "positive_count": pos_count,
        "safe_negative_count": safe_neg_count,
        "unresolved_excluded_count": unresolved_count,
        "labeled_count": labeled_count,
        "positive_rate": round(pos_rate, 4),
    }

    manifest_path = f"{output_path}.manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return manifest
