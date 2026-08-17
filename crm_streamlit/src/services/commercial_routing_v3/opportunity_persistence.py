"""Persist V3 category opportunities into crm_procurement_category_opportunities."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.decision_authorities import (
    CURRENT_ACCEPTED_DECISION,
    EXPERT_ANNOTATION,
    MODEL_RAW_DECISION,
    qwen_shadow_mode,
)


def _table_ready(crm_db) -> bool:
    try:
        return bool(
            crm_db.execute_scalar(
                "SELECT to_regclass('public.crm_procurement_category_opportunities') IS NOT NULL"
            )
        )
    except Exception:
        return False


def _opp_row_from_legacy_shape(
    *,
    procurement_id: int,
    assessment_id: Optional[int],
    opp: Dict[str, Any],
    normalized_result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    category_code = opp.get("category_code") or opp.get("commercial_category_code")
    if not category_code:
        return None

    track = opp.get("opportunity_track") or "UNKNOWN"
    medal = (
        opp.get("current_effective_medal")
        or opp.get("candidate_medal")
        or opp.get("candidate_level")
        or "WOOD"
    )
    research_action = opp.get("research_action") or "SKIP"
    initial_medal = opp.get("candidate_initial_medal") or medal
    initial_score = opp.get("candidate_initial_score")
    if initial_score is None:
        initial_score = opp.get("commercial_priority_score") or 0

    return {
        "procurement_id": procurement_id,
        "assessment_id": assessment_id,
        "commercial_category_code": category_code,
        "commercial_subcategory_code": opp.get("subcategory_code")
        or opp.get("commercial_subcategory_code"),
        "opportunity_track": track,
        "commercial_state": "ACTIVE",
        "last_source_event": "OPEN",
        "source_contour": normalized_result.get("source_contour") or "UNKNOWN",
        "procurement_form": normalized_result.get("procurement_form") or "UNKNOWN",
        "analysis_mode": normalized_result.get("analysis_mode") or "GENERAL_DISCOVERY",
        "category_confidence": float(opp.get("confidence") or 0.0),
        "research_action": research_action,
        "research_priority": int(opp.get("priority") or opp.get("research_priority") or 0),
        "research_value_score": int(opp.get("research_value_score") or 0),
        "commercial_priority_score": int(opp.get("commercial_priority_score") or 0),
        "candidate_medal": medal,
        "expected_category_value": opp.get("expected_category_value"),
        "category_value_basis": opp.get("category_value_basis") or "UNKNOWN_ADDRESSABLE_VALUE",
        "reason_codes": opp.get("reason_codes") or [],
        "positive_evidence": opp.get("positive_evidence") or [],
        "negative_evidence": opp.get("negative_evidence") or [],
        "registry_version": normalized_result.get("registry_version"),
        "registry_hash": normalized_result.get("registry_hash"),
        "prompt_version": normalized_result.get("prompt_version"),
        "routing_version": normalized_result.get("routing_version") or "v3",
        "model_name": normalized_result.get("model_name"),
        "candidate_initial_score": initial_score,
        "candidate_initial_medal": initial_medal,
        "candidate_initial_scoring_version": opp.get("candidate_initial_scoring_version"),
        "initial_medal_provenance": opp.get("initial_medal_provenance") or "FIRST_ACCEPTANCE",
        "confirmed_base_score": opp.get("confirmed_base_score"),
        "confirmed_base_medal": opp.get("confirmed_base_medal"),
        "confirmed_scoring_version": opp.get("confirmed_scoring_version"),
        "current_effective_score": opp.get("current_effective_score")
        if opp.get("current_effective_score") is not None
        else opp.get("commercial_priority_score"),
        "current_effective_medal": medal,
        "current_effective_reason": opp.get("current_effective_reason") or "FIRST_ACCEPTANCE",
        "semantic_hypothesis": opp.get("semantic_hypothesis") or {
            "category_code": category_code,
            "subcategory_code": opp.get("subcategory_code")
            or opp.get("commercial_subcategory_code"),
            "opportunity_track": track,
            "evidence_role": opp.get("evidence_role"),
            "confirmation_required": opp.get("confirmation_required"),
            "confidence": opp.get("confidence"),
        },
    }


def build_opportunity_rows(
    *,
    procurement_id: int,
    assessment_id: Optional[int],
    normalized_result: Dict[str, Any],
    category_opportunities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build canonical opportunity rows without DB writes."""
    rows: List[Dict[str, Any]] = []
    for opp in category_opportunities or []:
        row = _opp_row_from_legacy_shape(
            procurement_id=procurement_id,
            assessment_id=assessment_id,
            opp=opp,
            normalized_result=normalized_result,
        )
        if row:
            rows.append(row)
    return rows


def has_expert_lock(crm_db, procurement_id: int) -> bool:
    try:
        return bool(
            crm_db.execute_scalar(
                """
                SELECT 1 FROM crm_v3_expert_annotations
                WHERE procurement_id = %s AND is_current IS TRUE
                LIMIT 1
                """,
                (procurement_id,),
            )
        )
    except Exception:
        return False


def persist_category_opportunities(
    crm_db,
    *,
    procurement_id: int,
    assessment_id: Optional[int],
    normalized_result: Dict[str, Any],
    category_opportunities: List[Dict[str, Any]],
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Upsert CURRENT V3 opportunities for a procurement.

    Safe default: dry_run=True (no writes). Schema guard: skips if table missing.
    """
    if not _table_ready(crm_db):
        return {
            "dry_run": dry_run,
            "persisted": 0,
            "skipped": True,
            "reason": "category_opportunities_table_missing",
        }

    rows = build_opportunity_rows(
        procurement_id=procurement_id,
        assessment_id=assessment_id,
        normalized_result=normalized_result,
        category_opportunities=category_opportunities,
    )

    if dry_run:
        return {"dry_run": True, "persisted": len(rows), "rows": rows, "skipped": False}

    if has_expert_lock(crm_db, procurement_id):
        return {
            "dry_run": False,
            "persisted": 0,
            "accepted_untouched": True,
            "expert_locked": True,
            "authority": EXPERT_ANNOTATION,
            "reason": "EXPERT_ANNOTATION_PROTECTS_CURRENT_ACCEPTED",
            "skipped": False,
        }

    if qwen_shadow_mode():
        # MODEL_RAW is stored on procurement_ai_assessments. Do not promote
        # into CURRENT_ACCEPTED_DECISION and do not SUPERSEDE existing CURRENT.
        return {
            "dry_run": False,
            "shadow": True,
            "persisted": 0,
            "proposed": len(rows),
            "accepted_untouched": True,
            "authority": MODEL_RAW_DECISION,
            "reason": "QWEN_SHADOW_MODE_NO_AUTO_ACCEPT",
            "skipped": False,
        }

    routing_version = (normalized_result.get("routing_version") or "v3")

    crm_db.execute_update(
        """
        UPDATE crm_procurement_category_opportunities
        SET status = 'SUPERSEDED', updated_at = NOW()
        WHERE procurement_id = %s
          AND routing_version = %s
          AND status = 'CURRENT'
        """,
        (procurement_id, routing_version),
    )

    persisted = 0
    for row in rows:
        crm_db.execute_update(
            """
            INSERT INTO crm_procurement_category_opportunities (
                procurement_id, assessment_id,
                commercial_category_code, commercial_subcategory_code, opportunity_track,
                commercial_state, last_source_event,
                source_contour, procurement_form, analysis_mode,
                category_confidence, research_action, research_priority,
                research_value_score, commercial_priority_score, candidate_medal,
                expected_category_value, category_value_basis,
                reason_codes, positive_evidence, negative_evidence,
                registry_version, registry_hash, prompt_version, routing_version, model_name,
                candidate_initial_score, candidate_initial_medal,
                candidate_initial_scoring_version, initial_medal_provenance,
                confirmed_base_score, confirmed_base_medal, confirmed_scoring_version,
                current_effective_score, current_effective_medal, current_effective_reason,
                semantic_hypothesis,
                candidate_initial_at, current_effective_at,
                status
            ) VALUES (
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s,
                NOW(), NOW(),
                'CURRENT'
            )
            ON CONFLICT (procurement_id, commercial_category_code, commercial_subcategory_code, opportunity_track, routing_version)
            DO UPDATE SET
                assessment_id = EXCLUDED.assessment_id,
                category_confidence = EXCLUDED.category_confidence,
                research_action = EXCLUDED.research_action,
                research_priority = EXCLUDED.research_priority,
                research_value_score = EXCLUDED.research_value_score,
                commercial_priority_score = EXCLUDED.commercial_priority_score,
                candidate_medal = EXCLUDED.current_effective_medal,
                expected_category_value = EXCLUDED.expected_category_value,
                category_value_basis = EXCLUDED.category_value_basis,
                reason_codes = EXCLUDED.reason_codes,
                positive_evidence = EXCLUDED.positive_evidence,
                negative_evidence = EXCLUDED.negative_evidence,
                registry_version = EXCLUDED.registry_version,
                registry_hash = EXCLUDED.registry_hash,
                prompt_version = EXCLUDED.prompt_version,
                model_name = EXCLUDED.model_name,
                candidate_initial_score = COALESCE(
                    crm_procurement_category_opportunities.candidate_initial_score,
                    EXCLUDED.candidate_initial_score
                ),
                candidate_initial_medal = COALESCE(
                    crm_procurement_category_opportunities.candidate_initial_medal,
                    EXCLUDED.candidate_initial_medal
                ),
                candidate_initial_at = COALESCE(
                    crm_procurement_category_opportunities.candidate_initial_at,
                    NOW()
                ),
                candidate_initial_scoring_version = COALESCE(
                    crm_procurement_category_opportunities.candidate_initial_scoring_version,
                    EXCLUDED.candidate_initial_scoring_version
                ),
                initial_medal_provenance = CASE
                    WHEN crm_procurement_category_opportunities.candidate_initial_medal IS NOT NULL
                    THEN crm_procurement_category_opportunities.initial_medal_provenance
                    ELSE EXCLUDED.initial_medal_provenance
                END,
                confirmed_base_score = COALESCE(
                    crm_procurement_category_opportunities.confirmed_base_score,
                    EXCLUDED.confirmed_base_score
                ),
                confirmed_base_medal = COALESCE(
                    crm_procurement_category_opportunities.confirmed_base_medal,
                    EXCLUDED.confirmed_base_medal
                ),
                confirmed_scoring_version = COALESCE(
                    crm_procurement_category_opportunities.confirmed_scoring_version,
                    EXCLUDED.confirmed_scoring_version
                ),
                current_effective_score = EXCLUDED.current_effective_score,
                current_effective_medal = EXCLUDED.current_effective_medal,
                current_effective_reason = EXCLUDED.current_effective_reason,
                current_effective_at = NOW(),
                semantic_hypothesis = EXCLUDED.semantic_hypothesis,
                status = 'CURRENT',
                updated_at = NOW()
            """,
            (
                row["procurement_id"],
                row["assessment_id"],
                row["commercial_category_code"],
                row["commercial_subcategory_code"],
                row["opportunity_track"],
                row["commercial_state"],
                row["last_source_event"],
                row["source_contour"],
                row["procurement_form"],
                row["analysis_mode"],
                row["category_confidence"],
                row["research_action"],
                row["research_priority"],
                row["research_value_score"],
                row["commercial_priority_score"],
                row["candidate_medal"],
                row["expected_category_value"],
                row["category_value_basis"],
                json.dumps(row["reason_codes"]),
                json.dumps(row["positive_evidence"]),
                json.dumps(row["negative_evidence"]),
                row["registry_version"],
                row["registry_hash"],
                row["prompt_version"],
                row["routing_version"],
                row["model_name"],
                row.get("candidate_initial_score"),
                row.get("candidate_initial_medal"),
                row.get("candidate_initial_scoring_version"),
                row.get("initial_medal_provenance"),
                row.get("confirmed_base_score"),
                row.get("confirmed_base_medal"),
                row.get("confirmed_scoring_version"),
                row.get("current_effective_score"),
                row.get("current_effective_medal"),
                row.get("current_effective_reason"),
                json.dumps(row.get("semantic_hypothesis") or {}),
            ),
        )
        persisted += 1

    logger.info(
        "persisted %s category opportunities for procurement_id=%s (dry_run=%s)",
        persisted,
        procurement_id,
        dry_run,
    )
    return {"dry_run": False, "persisted": persisted, "skipped": False}


def persist_current_effective_lineage(
    crm_db,
    *,
    procurement_id: Any,
    commercial_category_code: str,
    opportunity_track: Optional[str],
    lineage: Dict[str, Any],
    dry_run: bool = True,
) -> bool:
    """Update only current_effective_* (+ mirrored candidate_medal). Preserves initial/confirmed."""
    if dry_run:
        return False
    crm_db.execute_update(
        """
        UPDATE crm_procurement_category_opportunities
        SET current_effective_score = %s,
            current_effective_medal = %s,
            current_effective_reason = %s,
            current_effective_at = NOW(),
            candidate_medal = %s
        WHERE procurement_id = %s
          AND commercial_category_code = %s
          AND coalesce(opportunity_track, '') = coalesce(%s, '')
          AND status = 'CURRENT'
        """,
        (
            lineage.get("current_effective_score"),
            lineage.get("current_effective_medal"),
            lineage.get("current_effective_reason"),
            lineage.get("current_effective_medal"),
            procurement_id,
            commercial_category_code,
            opportunity_track,
        ),
    )
    return True


def persist_medal_history_rows(crm_db, rows: List[Dict[str, Any]], *, dry_run: bool = True) -> int:
    """Insert medal transition history. No-op when table missing. Skips empty rows."""
    pending = [r for r in rows if r]
    if dry_run or not pending:
        return 0
    try:
        ready = bool(
            crm_db.execute_scalar(
                "SELECT to_regclass('public.crm_category_opportunity_medal_history') IS NOT NULL"
            )
        )
    except Exception:
        return 0
    if not ready:
        return 0
    written = 0
    for row in pending:
        crm_db.execute_update(
            """
            INSERT INTO crm_category_opportunity_medal_history (
                procurement_id, commercial_category_code, opportunity_track,
                previous_effective_score, previous_effective_medal,
                new_effective_score, new_effective_medal, reason,
                evaluated_at, lifecycle, timing_phase, scoring_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row.get("procurement_id"),
                row.get("commercial_category_code"),
                row.get("opportunity_track"),
                row.get("previous_effective_score"),
                row.get("previous_effective_medal"),
                row.get("new_effective_score"),
                row.get("new_effective_medal"),
                row.get("reason"),
                row.get("evaluated_at"),
                row.get("lifecycle"),
                row.get("timing_phase"),
                row.get("scoring_version"),
            ),
        )
        written += 1
    return written


def persist_inference_attempt(crm_db, state: Dict[str, Any], *, dry_run: bool = True) -> bool:
    """Upsert durable Qwen attempt telemetry (success or failure). Never stores prompts."""
    if dry_run or not state:
        return False
    try:
        ready = bool(
            crm_db.execute_scalar(
                "SELECT to_regclass('public.crm_v3_inference_attempts') IS NOT NULL"
            )
        )
    except Exception:
        return False
    if not ready:
        return False
    hist = state.get("attempt_history") or []
    if not isinstance(hist, str):
        hist = json.dumps(hist)
    crm_db.execute_update(
        """
        INSERT INTO crm_v3_inference_attempts (
            procurement_id, status, attempt_count, last_attempt_at, next_retry_at,
            retry_eligible, input_hash, prompt_version, prompt_sha256, model,
            failure_reason, failure_class, attempt_history
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s::jsonb
        )
        ON CONFLICT (procurement_id, input_hash, prompt_version)
        DO UPDATE SET
            status = EXCLUDED.status,
            attempt_count = EXCLUDED.attempt_count,
            last_attempt_at = EXCLUDED.last_attempt_at,
            next_retry_at = EXCLUDED.next_retry_at,
            retry_eligible = EXCLUDED.retry_eligible,
            model = EXCLUDED.model,
            failure_reason = EXCLUDED.failure_reason,
            failure_class = EXCLUDED.failure_class,
            attempt_history = EXCLUDED.attempt_history,
            updated_at = NOW()
        """,
        (
            state.get("procurement_id"),
            state.get("status"),
            state.get("attempt_count"),
            state.get("last_attempt_at"),
            state.get("next_retry_at"),
            bool(state.get("retry_eligible", True)),
            state.get("input_hash") or "",
            state.get("prompt_version") or "",
            state.get("prompt_sha256"),
            state.get("model"),
            state.get("failure_reason"),
            state.get("failure_class"),
            hist,
        ),
    )
    return True


def persist_inference_format_failed(crm_db, state: Dict[str, Any], *, dry_run: bool = True) -> bool:
    return persist_inference_attempt(crm_db, state, dry_run=dry_run)

