"""Единый источник истины для «живой» (claimable) очереди документов.

Предикат зеркалит `S13V2QueueRepository.claim_batch`
(`tender_documents_research/document_processor/backends/queue_repository.py`,
константа `_S13_CLAIM_ADMISSION_FILTER` + lane-фильтр) и должен быть NULL-safe:
строки с `plan_version IS NULL` по-прежнему claimable через ветки
`research_action` / `AI_QUEUE_ADMISSION_GATE`.
"""

from __future__ import annotations

import os

#: Рабочее поколение очереди — как в `backends/factory.py`
#: (`DOCUMENT_PIPELINE_GENERATION`, default S13_V4_EXHAUSTIVE_CONTEXT).
PIPELINE_GENERATION = os.getenv("DOCUMENT_PIPELINE_GENERATION", "S13_V4_EXHAUSTIVE_CONTEXT")

#: Лейны, которые реально обслуживают воркеры.
QUEUE_LANES = ("crm_active_hot", "open_active", "awarded_recent", "historical_awarded")

LANE_RANK = {
    "crm_active_hot": 1,
    "open_active": 2,
    "awarded_recent": 3,
    "historical_awarded": 4,
}

#: Claimable-предикат (alias ``q``). Два параметра по порядку:
#: pipeline_generation, список queue_lanes.
CLAIMABLE_QUEUE_SQL = """
    q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
    AND (q.pipeline_generation = %s OR q.pipeline_generation IS NULL)
    AND q.queue_lane = ANY(%s)
    AND (
        q.research_action = 'FACTUAL_FEEDER_ADMITTED'
        OR q.category_context->>'AI_QUEUE_ADMISSION_GATE' = 'YES'
        OR q.plan_version = 'queue_v2'
    )
    AND COALESCE(q.category_context->>'legacy_revalidation_status', '')
        NOT IN ('REQUIRED', 'LEGACY_HOLD')
    AND (
        q.plan_version IS DISTINCT FROM 'queue_v2'
        OR COALESCE(q.research_action_v2, '') IN
            ('DOCUMENT_RESEARCH_REQUIRED', 'DOCUMENT_CONFIRMATION_REQUIRED')
    )
"""


def claimable_params() -> list:
    return [PIPELINE_GENERATION, list(QUEUE_LANES)]


def claim_order_key(lane, work_tier, priority_score, row_id):
    """Порядок позиции в очереди: lane rank → work_tier → priority → id."""
    return (
        LANE_RANK.get(lane, 5),
        (int(work_tier) if work_tier is not None else 99),
        -(int(priority_score or 0)),
        -(int(row_id or 0)),
    )
