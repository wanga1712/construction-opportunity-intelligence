"""Sync object × product-group decisions into crm_object_profile_decisions."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from loguru import logger

from src.services.docs_match_preview import confirmed_product_groups, products_for_group
from src.services.object_models import ObjectViewItem
from src.services.profiled_search import (
    DECISION_DOCUMENTS_PARSED,
    DECISION_PROFILE_KEEP,
    ProfileDecision,
    ProfiledSearchService,
)


def sync_profile_decisions(
    crm_db,
    items: Iterable[ObjectViewItem],
    *,
    limit: int = 500,
) -> int:
    """Upsert keep/parsed decisions for each confirmed product group on an object."""
    if not crm_db or crm_db.is_offline_mode():
        return 0

    service = ProfiledSearchService(crm_db)
    try:
        service.ensure_schema()
    except Exception as exc:
        logger.warning(f"sync_profile_decisions ensure_schema: {exc}")
        return 0

    profile_groups = service.profile_groups()
    if not profile_groups:
        logger.warning("sync_profile_decisions: no profile/group bindings in CRM")
        return 0

    bindings: Dict[str, List[dict]] = {}
    for row in profile_groups:
        code = str(row.get("product_group_code") or "")
        bindings.setdefault(code, []).append(row)

    count = 0
    for item in items:
        if count >= limit:
            break
        groups = confirmed_product_groups(item)
        if not groups:
            continue
        for group_code in groups:
            binding = (bindings.get(group_code) or [None])[0]
            if not binding:
                continue
            products = products_for_group(item, group_code)
            decision = DECISION_DOCUMENTS_PARSED if products else DECISION_PROFILE_KEEP
            reason = (
                f"Подтверждено в документах: {', '.join(products[:3])}"
                if products
                else f"Группа {group_code} определена по названию/AI"
            )
            try:
                service.upsert_decision(
                    ProfileDecision(
                        object_key=item.key,
                        registry_type=item.registry_type,
                        tender_id=item.tender_id,
                        source_type=(item.sources[0] if item.sources else None),
                        search_profile_id=int(binding["search_profile_id"]),
                        product_group_id=int(binding["product_group_id"]),
                        decision=decision,
                        priority_score=int(item.ai_priority_score or 0),
                        reason=reason,
                        matched_terms=products[:12],
                        rejected_terms=[],
                        ai_payload={
                            "ai_card_status": item.ai_card_status_code,
                            "pipeline_stage": item.pipeline_stage_code,
                        },
                        decided_by="docs_match_sync",
                    )
                )
                count += 1
            except Exception as exc:
                logger.warning(f"sync_profile_decisions upsert {item.key}/{group_code}: {exc}")
    return count
