"""Procurement-grain pre-research scope authority materialization.

The materializer is deliberately explicit: callers must opt into writes. It
does not touch document_processing_queue, download documents, or retrain any
model.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from src.learning.procurement_scope.classifier import ProcurementScopeClassifierV1
from src.services.procurement_research_admission import evaluate_admission, lifecycle_for


@dataclass(frozen=True)
class ScopeAuthority:
    procurement_id: int
    source_lifecycle: str
    procurement_scope_type: str
    scope_confidence: float
    scope_method: str
    scope_version: str
    scope_evidence: dict[str, Any]
    admission_state: str
    admission_reason: str
    evaluated_at: datetime

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["evaluated_at"] = self.evaluated_at
        return record


def classify_procurement(row: Mapping[str, Any], *, classifier: ProcurementScopeClassifierV1 | None = None) -> ScopeAuthority:
    """Build one current authority row from pre-research CRM metadata only."""
    classifier = classifier or ProcurementScopeClassifierV1()
    result = classifier.classify_procurement(row)
    admission = evaluate_admission(row, result["procurement_scope_type"])
    evidence = dict(result["scope_evidence"])
    evidence["input_fields"] = [
        "title",
        "auction_name",
        "subject",
        "purchase_object",
        "lot_item_names",
        "okpd_codes",
        "crm_stage",
        "award_status",
    ]
    return ScopeAuthority(
        procurement_id=int(row["id"]),
        source_lifecycle=admission.lifecycle,
        procurement_scope_type=result["procurement_scope_type"],
        scope_confidence=float(result["scope_confidence"]),
        scope_method=result["scope_method"],
        scope_version=result["scope_model_or_rule_version"],
        scope_evidence=evidence,
        admission_state=admission.state,
        admission_reason=admission.reason,
        evaluated_at=datetime.now(timezone.utc),
    )


def classify_rows(rows: Iterable[Mapping[str, Any]]) -> list[ScopeAuthority]:
    """Classify a snapshot without any database or queue side effect."""
    return [classify_procurement(row) for row in rows]


def materialize_scope_authority(crm_db: Any, rows: Iterable[Mapping[str, Any]], *, write: bool = False) -> dict[str, int]:
    """Upsert authority rows; default is a read-only dry run.

    ``crm_db`` is expected to expose a DB-API connection through ``connection``
    or be a DB-API connection itself. This function only writes the authority
    table and never changes the research queue.
    """
    authorities = classify_rows(rows)
    counts = {"classified": len(authorities), "materialized": 0}
    if not write:
        return counts
    connection = getattr(crm_db, "connection", crm_db)
    with connection.cursor() as cursor:
        for authority in authorities:
            cursor.execute(
                """
                INSERT INTO crm_procurement_scope_authority (
                    procurement_id, source_lifecycle, procurement_scope_type,
                    scope_confidence, scope_method, scope_version,
                    scope_evidence, admission_state, admission_reason,
                    scope_evaluated_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,NOW())
                ON CONFLICT (procurement_id) DO UPDATE SET
                    source_lifecycle = EXCLUDED.source_lifecycle,
                    procurement_scope_type = EXCLUDED.procurement_scope_type,
                    scope_confidence = EXCLUDED.scope_confidence,
                    scope_method = EXCLUDED.scope_method,
                    scope_version = EXCLUDED.scope_version,
                    scope_evidence = EXCLUDED.scope_evidence,
                    admission_state = EXCLUDED.admission_state,
                    admission_reason = EXCLUDED.admission_reason,
                    scope_evaluated_at = EXCLUDED.scope_evaluated_at,
                    updated_at = NOW()
                """,
                (
                    authority.procurement_id,
                    authority.source_lifecycle,
                    authority.procurement_scope_type,
                    authority.scope_confidence,
                    authority.scope_method,
                    authority.scope_version,
                    json.dumps(authority.scope_evidence, ensure_ascii=False),
                    authority.admission_state,
                    authority.admission_reason,
                    authority.evaluated_at,
                ),
            )
    connection.commit()
    counts["materialized"] = len(authorities)
    return counts
