"""First Pass Service: Unified fast metadata assessment before heavy document processing."""
from __future__ import annotations

from datetime import date, datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Sequence

from src.learning.procurement_scope.classifier import ProcurementScopeClassifierV1
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
)
from src.services.first_pass.resolver import (
    calculate_priority_score,
    resolve_canonical_preliminary_medal,
    resolve_download_decision,
    resolve_object_family,
)
from src.services.first_pass.types import FirstPassResult

logger = logging.getLogger(__name__)


def parse_datetime(dt_val: Any) -> Optional[datetime]:
    """Parse various datetime/date/string representations into a UTC datetime."""
    if dt_val is None:
        return None
    if isinstance(dt_val, datetime):
        return dt_val if dt_val.tzinfo is not None else dt_val.replace(tzinfo=timezone.utc)
    if isinstance(dt_val, date):
        return datetime(dt_val.year, dt_val.month, dt_val.day, tzinfo=timezone.utc)
    if isinstance(dt_val, str):
        s = dt_val.strip()
        if not s:
            return None
        # Try ISO format
        try:
            parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            pass
        # Common Russian formats
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(s, fmt)
                return parsed.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return None


class FirstPassService:
    """Service that executes fast First Pass metadata assessment and queue priority projection."""

    def __init__(self, crm_db: Any = None) -> None:
        self.crm_db = crm_db
        self.scope_classifier = ProcurementScopeClassifierV1()
        self._cached_priors: Optional[List[Dict[str, Any]]] = None

    def get_priors(self) -> List[Dict[str, Any]]:
        if self._cached_priors is None:
            if self.crm_db is not None:
                self._cached_priors = load_okpd_priors_from_db(self.crm_db)
            else:
                self._cached_priors = []
        return self._cached_priors

    def evaluate_procurement(
        self,
        proc: Dict[str, Any],
        doc_count: int = 1,
        category_opps: Optional[Sequence[Dict[str, Any]]] = None,
        ai_assessment: Optional[Dict[str, Any]] = None,
        priors: Optional[List[Dict[str, Any]]] = None,
        now: Optional[datetime] = None,
    ) -> FirstPassResult:
        """Evaluate a single procurement record strictly from metadata."""
        proc_id = int(proc.get("id") or proc.get("procurement_id") or 0)
        contract_number = proc.get("contract_number") or proc.get("contract_reg_number")
        okpd = proc.get("okpd_code") or proc.get("okpd2_code") or ""
        title = proc.get("auction_name") or proc.get("purchase_object_info") or proc.get("title") or proc.get("subject") or ""
        # MEDAL SEMANTICS V2: metadata-stage descriptive text used for canonical
        # category semantics (OKPD name + declared product names). Price is never used.
        product_names = proc.get("product_names") or []
        if isinstance(product_names, str):
            product_names = [product_names]
        scope_text = " ".join(
            str(x) for x in (
                proc.get("okpd_name"),
                " ".join(str(p) for p in product_names if p),
                proc.get("crm_category"),
            ) if x
        )
        end_date_val = proc.get("end_date") or proc.get("submission_end_at") or proc.get("submission_close_date")
        submission_end_at = parse_datetime(end_date_val)

        # 1. Procurement Scope Classification
        scope_res = proc.get("scope_classification")
        if not scope_res:
            scope_res = self.scope_classifier.classify(title, [okpd] if okpd else [])
        scope_type = scope_res.get("procurement_scope_type")

        # 2. OKPD Target Classification
        if priors is None:
            priors = self.get_priors()
        okpd_classification, matched_priors = classify_target_okpd(okpd, priors)

        # 3. Canonical Preliminary Medal Resolution (Deterministic Multiplicity Handling)
        medal, norm_score, raw_conf, source, cat, subcat, total_opps, selected_opp_id = (
            resolve_canonical_preliminary_medal(
                category_opps=category_opps,
                ai_assessment=ai_assessment,
                okpd_target_classification=okpd_classification,
                matched_priors=matched_priors,
                title=title,
                scope_text=scope_text,
                okpd_code=okpd,
            )
        )

        # 4. Object Family Normalization
        sector = proc.get("object_sector") or proc.get("expert_object_sector")
        obj_type = proc.get("object_type") or proc.get("expert_object_type")
        obj_subtype = proc.get("object_subtype") or proc.get("expert_object_subtype")
        object_family = resolve_object_family(
            scope_type=scope_type,
            sector=sector,
            object_type=obj_type,
            title=title,
        )

        # 5. Download Decision
        download_decision = resolve_download_decision(
            okpd_target_classification=okpd_classification,
            canonical_preliminary_medal=medal,
            doc_count=doc_count,
        )

        # 6. Priority Score Calculation (No double counting, no automatic DIRECT_SUPPLY bonus)
        # Relevance bonus (+10) strictly requires an independent commercial relevance signal
        # and is NEVER granted merely from prior_weight >= 80 or preliminary medal alone.
        is_explicit_target = bool(proc.get("is_explicit_target_profile"))
        priority_score, medal_base, urgency_bonus, relevance_bonus, days_to_deadline = calculate_priority_score(
            canonical_preliminary_medal=medal,
            submission_end_at=submission_end_at,
            is_explicit_target_profile=is_explicit_target,
            now=now,
        )
        priority_class = medal

        queue_lane = proc.get("queue_lane") or "open_active"
        queue_status = proc.get("queue_status") or "pending"

        return FirstPassResult(
            procurement_id=proc_id,
            contract_number=contract_number,
            object_family=object_family,
            object_type=obj_type,
            object_subtype=obj_subtype,
            category=cat,
            subcategory=subcat,
            canonical_preliminary_medal=medal,
            canonical_preliminary_score=norm_score,
            canonical_preliminary_source=source,
            raw_source_confidence=raw_conf,
            category_opportunity_count=total_opps,
            selected_opportunity_id=selected_opp_id,
            download_decision=download_decision,
            medal_base=medal_base,
            urgency_bonus=urgency_bonus,
            relevance_bonus=relevance_bonus,
            priority_score=priority_score,
            priority_class=priority_class,
            submission_end_at=submission_end_at,
            days_to_deadline=days_to_deadline,
            queue_lane=queue_lane,
            queue_status=queue_status,
        )

    def evaluate_batch(
        self,
        procurements: Sequence[Dict[str, Any]],
        doc_counts: Optional[Dict[int, int]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[int, FirstPassResult]:
        """Batch evaluate procurements with zero N+1 queries."""
        if not procurements:
            return {}

        pids = [int(p.get("id") or p.get("procurement_id") or 0) for p in procurements if (p.get("id") or p.get("procurement_id"))]
        pids = list(set(pids))
        if not pids:
            return {}

        priors = self.get_priors()

        category_opps_map: Dict[int, List[Dict[str, Any]]] = {pid: [] for pid in pids}

        if self.crm_db is not None:
            # 1. Bulk load all opportunities for multiplicity resolution
            try:
                opp_rows = self.crm_db.execute_query(
                    """
                    SELECT id, procurement_id, commercial_category_code,
                           candidate_medal, current_effective_medal, confirmed_base_medal,
                           COALESCE(current_effective_score, candidate_initial_score, commercial_priority_score::numeric, category_confidence * 100) AS candidate_score,
                           commercial_subcategory_code AS subcategory_code, commercial_state, opportunity_track
                    FROM crm_procurement_category_opportunities
                    WHERE procurement_id = ANY(%s)
                    ORDER BY procurement_id, id DESC
                    """,
                    (pids,),
                ) or []
                for r in opp_rows:
                    row_dict = dict(r) if isinstance(r, dict) else {}
                    pid = row_dict.get("procurement_id")
                    if pid and pid in category_opps_map:
                        category_opps_map[pid].append(row_dict)
            except Exception as e:
                logger.warning("Error loading category opportunities in batch: %s", e)

            # 2. Second Pass output is deliberately NOT loaded here.
            #    MEDAL SEMANTICS V2 (ANALYTICS-V2-MEDAL-SEMANTICS-V2-REBUILD-1):
            #    procurement_ai_assessments.proposed_level / normalized_result are
            #    model results and must never become a PRELIMINARY signal.

        results: Dict[int, FirstPassResult] = {}
        for p in procurements:
            pid = int(p.get("id") or p.get("procurement_id") or 0)
            if not pid:
                continue
            dc = doc_counts.get(pid, 1) if doc_counts else 1
            res = self.evaluate_procurement(
                proc=p,
                doc_count=dc,
                category_opps=category_opps_map.get(pid, []),
                priors=priors,
                now=now,
            )
            results[pid] = res

        return results
