"""Read-only data projection for the dedicated expert annotation card."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse


def source_law(source_table: str | None) -> str:
    """Short factual law label from source_table (pre-AI). Prefer source_contour for cards."""
    from src.services.source_contour import source_law_label

    return source_law_label(source_table)


def document_key(row: dict) -> str:
    return str(row.get("source_document_url") or row.get("document_title") or row.get("id") or "document")


def document_filename(row: dict) -> str:
    title = str(row.get("document_title") or "").strip()
    if title:
        return title.rsplit("/", 1)[-1]
    path = urlparse(str(row.get("source_document_url") or "")).path
    return path.rsplit("/", 1)[-1] or "Документ без имени"


def project_document_rows(rows: list[dict]) -> list[dict]:
    projected = []
    for row in rows:
        categories = list(row.get("matched_categories") or [])
        mentions = list(row.get("product_mentions") or [])
        projected.append({
            **row,
            "document_key": document_key(row),
            "file_name": document_filename(row),
            "match_found": bool(categories or mentions),
            "evidence_found": bool(row.get("commercial_evidence_found")),
            "category_signals": categories,
            "product_mentions": mentions,
        })
    return projected


def _safe_rows(db: Any, sql: str, procurement_id: int) -> list[dict]:
    try:
        return [dict(row) for row in (db.execute_query(sql, (procurement_id,)) or [])]
    except Exception:
        return []


def _add(events: list[dict], at: Any, kind: str, title: str, detail: str, authority: str) -> None:
    if at:
        events.append({"at": at, "kind": kind, "title": title, "detail": detail, "authority": authority})


def load_annotation_history(db: Any, procurement_id: int, header: dict) -> list[dict]:
    """Combine only persisted events; missing sources produce no fabricated events."""
    events: list[dict] = []
    _add(events, header.get("crm_created_at"), "SOURCE", "Закупка добавлена в CRM", header.get("source_table") or "—", "SOURCE_FACT")
    _add(events, header.get("source_updated_at"), "SOURCE", "Источник обновлён", "Последнее подтверждённое обновление источника", "SOURCE_FACT")

    assessments = _safe_rows(db, """
        SELECT id, assessment_version, status, started_at, completed_at,
               inference_run_id, proposed_route_profile, proposed_categories,
               proposed_level, change_fields, normalized_result
        FROM procurement_ai_assessments WHERE procurement_id=%s
        ORDER BY assessment_version, id
    """, procurement_id)
    for row in assessments:
        model_source = "immutable inference run" if row.get("inference_run_id") else "legacy / RAW unavailable"
        changes = ", ".join(row.get("change_fields") or []) or "первичная/без зафиксированных изменений"
        _add(events, row.get("completed_at") or row.get("started_at"), "MODEL", f"AI assessment v{row.get('assessment_version')}", f"{model_source}; status={row.get('status')}; changes={changes}", "MODEL_OR_LEGACY")

    opportunities = _safe_rows(db, """
        SELECT commercial_category_code, commercial_subcategory_code,
               candidate_medal, current_effective_medal, current_effective_score,
               created_at, updated_at
        FROM crm_procurement_category_opportunities
        WHERE procurement_id=%s ORDER BY created_at, id
    """, procurement_id)
    for row in opportunities:
        category = row.get("commercial_category_code") or "—"
        medal = row.get("current_effective_medal") or row.get("candidate_medal") or "—"
        _add(events, row.get("created_at"), "BUSINESS", f"Сформирована категория {category}", f"medal={medal}; score={row.get('current_effective_score') or '—'}", "BUSINESS_RULE")

    lifecycle = _safe_rows(db, """
        SELECT commercial_category_code, old_commercial_state,
               new_commercial_state, reason, changed_at
        FROM crm_category_opportunity_lifecycle_audit
        WHERE procurement_id=%s ORDER BY changed_at, id
    """, procurement_id)
    for row in lifecycle:
        _add(events, row.get("changed_at"), "BUSINESS", "Изменён lifecycle категории", f"{row.get('commercial_category_code')}: {row.get('old_commercial_state') or '—'} → {row.get('new_commercial_state') or '—'}; {row.get('reason') or ''}", "BUSINESS_RULE")

    medals = _safe_rows(db, """
        SELECT commercial_category_code, previous_effective_medal,
               new_effective_medal, reason, evaluated_at
        FROM crm_category_opportunity_medal_history
        WHERE procurement_id=%s ORDER BY evaluated_at, id
    """, procurement_id)
    for row in medals:
        _add(events, row.get("evaluated_at"), "BUSINESS", "Изменена бизнес-медаль", f"{row.get('commercial_category_code')}: {row.get('previous_effective_medal') or '—'} → {row.get('new_effective_medal') or '—'}; {row.get('reason') or ''}", "BUSINESS_RULE")

    overrides = _safe_rows(db, """
        SELECT business_relevance, overall_research_action, reviewed_by,
               reviewed_at, updated_at FROM crm_manual_overrides
        WHERE procurement_id=%s ORDER BY updated_at
    """, procurement_id)
    for row in overrides:
        _add(events, row.get("reviewed_at") or row.get("updated_at"), "OVERRIDE", "Ручной profile override", f"relevance={row.get('business_relevance') or '—'}; action={row.get('overall_research_action') or '—'}; by={row.get('reviewed_by') or '—'}", "MANUAL_OVERRIDE")

    category_overrides = _safe_rows(db, """
        SELECT category_code, subcategory_code, manual_candidate_level,
               manual_reason, reviewed_by, reviewed_at, updated_at
        FROM crm_manual_category_overrides
        WHERE procurement_id=%s ORDER BY updated_at, id
    """, procurement_id)
    for row in category_overrides:
        _add(events, row.get("reviewed_at") or row.get("updated_at"), "OVERRIDE", "Ручная коррекция категории", f"{row.get('category_code') or '—'} / {row.get('subcategory_code') or '—'}; medal={row.get('manual_candidate_level') or '—'}; {row.get('manual_reason') or ''}", "MANUAL_OVERRIDE")

    annotations = _safe_rows(db, """
        SELECT annotation_version, payload, created_by, created_at
        FROM crm_v3_expert_annotations WHERE procurement_id=%s
        ORDER BY annotation_version, id
    """, procurement_id)
    for row in annotations:
        payload = row.get("payload") or {}
        cats = [item.get("category_code") for item in payload.get("opportunities", []) if isinstance(item, dict)] if isinstance(payload, dict) else []
        _add(events, row.get("created_at"), "EXPERT", f"Экспертная разметка v{row.get('annotation_version')}", f"verdict={payload.get('expert_verdict') if isinstance(payload, dict) else '—'}; categories={cats}; by={row.get('created_by') or '—'}", "EXPERT_ANNOTATION")

    audit = _safe_rows(db, """
        SELECT action_type, user_name, comment, changed_fields, timestamp
        FROM crm_manual_assessments_audit
        WHERE procurement_id=%s ORDER BY timestamp, id
    """, procurement_id)
    for row in audit:
        fields = ", ".join(row.get("changed_fields") or []) or "—"
        _add(events, row.get("timestamp"), "EXPERT", f"Ручное действие: {row.get('action_type') or '—'}", f"fields={fields}; {row.get('comment') or ''}; by={row.get('user_name') or '—'}", "MANUAL_AUDIT")

    return sorted(events, key=lambda event: event["at"] if isinstance(event["at"], datetime) else str(event["at"]))
