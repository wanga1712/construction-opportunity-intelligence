"""Commercial routing V3 engine — deterministic + AI-assisted orchestration."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from src.domain.commercial_routing_v3 import (
    ROUTING_VERSION,
    AnalysisMode,
    CandidateMedal,
    CategoryOpportunityV3,
    CategoryValueBasis,
    OpportunityTrack,
    ProcurementForm,
    ResearchAction,
    RoutingDecisionV3,
    TRACKS_FOR_FORM,
)
from src.services.commercial_routing_v3.analysis_mode import resolve_analysis_modes
from src.services.commercial_routing_v3.candidate_scoring import (
    apply_candidate_scoring_to_hypotheses,
    score_hypothesis,
    CandidateScoringContext,
)
from src.services.commercial_routing_v3.medal import resolve_category_value_basis
from src.services.commercial_routing_v3.normalizer import normalize_v3_output
from src.services.commercial_routing_v3.object_mode_routing import enrich_object_mode_routing
from src.services.commercial_routing_v3.okpd_priors import match_okpd_priors
from src.services.commercial_routing_v3.procurement_form import classify_procurement_form
from src.services.commercial_routing_v3.prompt import (
    PROMPT_VERSION,
    build_v3_prompt,
    prompt_subcategory_count,
)
from src.services.commercial_routing_v3.routing_signals import apply_title_signals
from src.services.commercial_routing_v3.source_contour import resolve_source_contour
from src.domain.commercial_taxonomy import COMMERCIAL_KEEP_CODES
from src.services.commercial_taxonomy_registry import load_active_commercial_categories

logger = logging.getLogger("commercial_routing_v3.engine")

_ACTION_RANK = {
    ResearchAction.SKIP: 0,
    ResearchAction.METADATA_ONLY: 1,
    ResearchAction.LIGHT_RESEARCH: 2,
    ResearchAction.PRIORITY_DOCS: 3,
    ResearchAction.DEEP_RESEARCH: 4,
}


class CommercialRoutingV3Engine:
    """Category-centric preliminary routing. Supports dry-run without persistence."""

    def __init__(self, crm_db=None) -> None:
        self.crm_db = crm_db

    def load_registry(self) -> tuple[List[Dict[str, Any]], Set[str], Dict[str, Set[str]]]:
        if not self.crm_db:
            allowed = set(COMMERCIAL_KEEP_CODES)
            registry = [
                {"category_code": c, "category_name": c, "lifecycle_state": "ACTIVE", "subcategories": []}
                for c in sorted(allowed)
            ]
            return registry, allowed, {c: set() for c in allowed}
        cats = load_active_commercial_categories(
            self.crm_db, allow_legacy_fallback=False
        )
        allowed = {c["category_code"] for c in cats}
        subs: Dict[str, Set[str]] = {}
        rows = self.crm_db.execute_query(
            """
            SELECT c.category_code, s.subcategory_code
            FROM crm_product_subcategories s
            JOIN crm_product_categories c ON c.id = s.category_id
            WHERE c.is_active = TRUE AND s.is_active = TRUE
            """
        ) or []
        for r in rows:
            code = r["category_code"] if isinstance(r, dict) else r[0]
            sub = r["subcategory_code"] if isinstance(r, dict) else r[1]
            subs.setdefault(code, set()).add(sub)
        enriched = []
        for c in cats:
            item = dict(c)
            item["subcategories"] = [
                {"subcategory_code": s, "subcategory_name": s}
                for s in sorted(subs.get(c["category_code"], set()))
            ]
            enriched.append(item)
        return enriched, allowed, subs

    def build_prompt_context(self, procurement: Dict[str, Any]) -> str:
        registry, _, _ = self.load_registry()
        priors = self._load_priors()
        form = classify_procurement_form(procurement)
        return build_v3_prompt(
            procurement,
            registry=registry,
            okpd_priors=priors,
            routing_signals=[],
            procurement_form_prior=form.value,
        )

    def prompt_subcategories_sent(self, procurement: Dict[str, Any]) -> int:
        registry, _, _ = self.load_registry()
        return prompt_subcategory_count(procurement=procurement, registry=registry, okpd_priors=self._load_priors())

    def route_deterministic(self, procurement: Dict[str, Any]) -> RoutingDecisionV3:
        """Deterministic routing without AI call — for tests and priors."""
        registry, allowed, subs = self.load_registry()
        priors = self._load_priors()
        signals = self._load_signals()

        contour = resolve_source_contour(
            source_table=procurement.get("source_table", ""),
            law_type=procurement.get("law_type", ""),
        )
        form = classify_procurement_form(procurement)
        modes = resolve_analysis_modes(form)
        okpd = procurement.get("okpd_code") or ""
        title = procurement.get("title") or procurement.get("auction_name") or ""
        price = float(procurement.get("price") or procurement.get("initial_price") or 0)

        matched_priors = match_okpd_priors(okpd, priors)
        hypotheses: List[CategoryOpportunityV3] = []
        tracks = TRACKS_FOR_FORM.get(form, [OpportunityTrack.UNKNOWN])

        for prior in matched_priors:
            cat = prior.get("commercial_category_code")
            if not cat or cat not in allowed:
                continue
            sig_result = apply_title_signals(title, signals, cat)
            if sig_result["hard_exclusions"]:
                continue
            confidence = min(0.95, 0.4 + float(prior.get("prior_weight") or 0) / 100)
            for track in tracks:
                evidence = 40 + len(sig_result["positive_evidence"]) * 15
                evidence -= len(sig_result["negative_evidence"]) * 10
                has_non_price = bool(sig_result["positive_evidence"] or matched_priors)
                val, basis = resolve_category_value_basis(
                    opportunity_track=track,
                    procurement_form=form,
                    procurement_total=price,
                    category_confidence=confidence,
                )
                ctx = CandidateScoringContext(
                    procurement_form=form.value,
                    normalized_lifecycle=str(procurement.get("normalized_lifecycle") or "OPEN"),
                    initial_price=price,
                    category_confidence=confidence,
                )
                scored = score_hypothesis(
                    {
                        "category_code": cat,
                        "opportunity_track": track.value,
                        "confidence": confidence,
                        "evidence_role": "COMMERCIAL_PRODUCT_PRIOR",
                        "confirmation_required": False,
                        "positive_evidence": sig_result["positive_evidence"],
                    },
                    ctx,
                )
                medal = scored.candidate_medal
                comm = int(round(scored.final_score))
                research = int(round(scored.base_score))
                action = self._research_action_for(medal, form, track)
                hypotheses.append(
                    CategoryOpportunityV3(
                        commercial_category_code=cat,
                        commercial_subcategory_code=None,
                        opportunity_track=track,
                        category_confidence=confidence,
                        research_action=action,
                        research_priority=comm,
                        commercial_priority_score=comm,
                        research_value_score=research,
                        candidate_medal=medal,
                        expected_category_value=val,
                        category_value_basis=basis,
                        reason_codes=["okpd_prior"] if okpd else [],
                        positive_evidence=sig_result["positive_evidence"],
                        negative_evidence=sig_result["negative_evidence"],
                    )
                )

        discovery = self._needs_discovery(form, hypotheses, procurement)
        overall = self._aggregate_action(hypotheses, discovery)

        return RoutingDecisionV3(
            source_contour=contour,
            procurement_form=form,
            analysis_modes=modes,
            commercial_category_hypotheses=hypotheses,
            discovery_required=discovery,
            overall_research_action=overall,
            prompt_version=PROMPT_VERSION,
            routing_version=ROUTING_VERSION,
        )

    def route_with_ai(
        self,
        procurement: Dict[str, Any],
        ai_raw: Dict[str, Any],
        *,
        registry_version: int = 1,
        registry_hash: str = "",
        model_name: str = "",
    ) -> RoutingDecisionV3:
        registry, allowed, subs = self.load_registry()
        has_okpd = bool(procurement.get("okpd_code"))
        normalized = normalize_v3_output(
            ai_raw,
            allowed_categories=allowed,
            allowed_subcategories=subs,
            has_okpd=has_okpd,
        )
        normalized = enrich_object_mode_routing(
            normalized, procurement, allowed_categories=allowed
        )
        from src.services.commercial_routing_v3.object_mode_routing import source_data_quality_label

        sq = source_data_quality_label(procurement)
        normalized["commercial_category_hypotheses"] = apply_candidate_scoring_to_hypotheses(
            list(normalized.get("commercial_category_hypotheses") or []),
            procurement=procurement,
            normalized=normalized,
            source_data_quality=sq,
        )
        det = self.route_deterministic(procurement)
        form = ProcurementForm(normalized.get("procurement_form", det.procurement_form.value))
        hypotheses: List[CategoryOpportunityV3] = []
        price = float(procurement.get("price") or 0)
        _valid_actions = {a.value for a in ResearchAction}

        for h in normalized.get("commercial_category_hypotheses") or []:
            track = OpportunityTrack(h["opportunity_track"])
            conf = float(h.get("confidence") or 0)
            basis = CategoryValueBasis(h.get("category_value_basis", CategoryValueBasis.UNKNOWN_ADDRESSABLE_VALUE.value))
            val = h.get("expected_category_value")
            if basis == CategoryValueBasis.DIRECT_PROCUREMENT_VALUE and val is None and price:
                val = price
            medal_str = h.get("candidate_medal") or CandidateMedal.WOOD.value
            try:
                medal = CandidateMedal(medal_str)
            except ValueError:
                medal = CandidateMedal.WOOD
            comm = int(h.get("commercial_priority_score") or 0)
            research = int(h.get("research_value_score") or 0)
            try:
                action = ResearchAction(h.get("research_action", ResearchAction.SKIP.value))
            except ValueError:
                action = ResearchAction.SKIP
            if action.value not in _valid_actions:
                action = self._research_action_for(medal, form, track)
            hypotheses.append(
                CategoryOpportunityV3(
                    commercial_category_code=h["category_code"],
                    commercial_subcategory_code=h.get("subcategory_code"),
                    opportunity_track=track,
                    category_confidence=conf,
                    research_action=action,
                    research_priority=int(h.get("research_priority") or comm),
                    commercial_priority_score=comm,
                    research_value_score=research,
                    candidate_medal=medal,
                    expected_category_value=val,
                    category_value_basis=basis,
                    reason_codes=list(h.get("reason_codes") or []),
                    positive_evidence=list(h.get("positive_evidence") or []),
                    negative_evidence=list(h.get("negative_evidence") or []),
                )
            )

        empty_st = str(normalized.get("empty_hypothesis_status") or "").upper()
        if empty_st == "NO_COMMERCIAL_ENTRY":
            discovery = False
            overall = ResearchAction.SKIP
        else:
            discovery = bool(normalized.get("discovery_required")) or self._needs_discovery(
                form, hypotheses, procurement
            )
            overall_raw = normalized.get("overall_research_action") or self._aggregate_action(
                hypotheses, discovery
            ).value
            try:
                overall = ResearchAction(overall_raw)
            except ValueError:
                overall = self._aggregate_action(hypotheses, discovery)

        return RoutingDecisionV3(
            source_contour=det.source_contour,
            procurement_form=form,
            analysis_modes=[AnalysisMode(m) for m in normalized.get("analysis_modes") or []],
            object_context=list(normalized.get("object_context") or []),
            material_signals=list(normalized.get("material_signals") or []),
            work_methods=list(normalized.get("work_methods") or []),
            application_areas=list(normalized.get("application_areas") or []),
            brands=list(normalized.get("brands") or []),
            commercial_category_hypotheses=hypotheses,
            discovery_required=discovery,
            overall_research_action=overall,
            registry_version=registry_version,
            registry_hash=registry_hash,
            prompt_version=PROMPT_VERSION,
            routing_version=ROUTING_VERSION,
            model_name=model_name,
            empty_hypothesis_status=normalized.get("empty_hypothesis_status"),
            empty_hypothesis_reason_codes=list(
                normalized.get("empty_hypothesis_reason_codes") or []
            ),
            rejected_category_codes=list(normalized.get("rejected_category_codes") or []),
            preferred_opportunity_track=normalized.get("preferred_opportunity_track"),
            review_required=False
            if empty_st == "NO_COMMERCIAL_ENTRY"
            else bool(normalized.get("review_required")),
            routing_mode=normalized.get("routing_mode"),
            object_classification=normalized.get("object_classification"),
            document_research_priority=list(normalized.get("document_research_priority") or []),
            hypothesis_details=list(normalized.get("commercial_category_hypotheses") or []),
            awarded_context=normalized.get("awarded_context"),
            post_award_commercial_target=normalized.get("post_award_commercial_target"),
            post_award_commercial_target_name=normalized.get("post_award_commercial_target_name"),
        )

    def _load_priors(self) -> List[Dict[str, Any]]:
        if not self.crm_db:
            return _DEFAULT_OKPD_PRIORS
        try:
            from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
            return load_okpd_priors_from_db(self.crm_db)
        except Exception:
            return _DEFAULT_OKPD_PRIORS

    def _load_signals(self) -> List[Dict[str, Any]]:
        if not self.crm_db:
            return _DEFAULT_ROUTING_SIGNALS
        try:
            from src.services.commercial_routing_v3.routing_signals import load_routing_signals
            return load_routing_signals(self.crm_db)
        except Exception:
            return []

    @staticmethod
    def _research_action_for(medal, form: ProcurementForm, track: OpportunityTrack) -> ResearchAction:
        if medal.value == "WOOD":
            return ResearchAction.SKIP
        if form in (ProcurementForm.DESIGN_ONLY, ProcurementForm.SURVEY_AND_DESIGN):
            return ResearchAction.LIGHT_RESEARCH
        if track == OpportunityTrack.DIRECT_SUPPLY and medal.value == "GOLD":
            return ResearchAction.PRIORITY_DOCS
        if medal.value in ("GOLD", "SILVER"):
            return ResearchAction.LIGHT_RESEARCH
        return ResearchAction.METADATA_ONLY

    @staticmethod
    def _needs_discovery(
        form: ProcurementForm,
        hypotheses: List[CategoryOpportunityV3],
        procurement: Dict[str, Any],
    ) -> bool:
        if form in (
            ProcurementForm.DESIGN_ONLY,
            ProcurementForm.SURVEY_AND_DESIGN,
            ProcurementForm.DESIGN_AND_BUILD,
            ProcurementForm.DESIGN_EXPERTISE_AND_BUILD,
        ):
            return True
        if not hypotheses and form == ProcurementForm.CONSTRUCTION_WORKS:
            return bool(procurement.get("okpd_code"))
        return False

    @staticmethod
    def _aggregate_action(
        hypotheses: List[CategoryOpportunityV3],
        discovery: bool,
    ) -> ResearchAction:
        best = ResearchAction.SKIP
        for h in hypotheses:
            if _ACTION_RANK[h.research_action] > _ACTION_RANK[best]:
                best = h.research_action
        if discovery and _ACTION_RANK[best] < _ACTION_RANK[ResearchAction.LIGHT_RESEARCH]:
            return ResearchAction.LIGHT_RESEARCH
        return best


_DEFAULT_OKPD_PRIORS = [
    {"commercial_category_code": "lighting", "okpd_pattern": "27.40", "match_type": "PREFIX", "prior_weight": 60, "active": True},
    {"commercial_category_code": "lighting", "okpd_pattern": "42.11", "match_type": "PREFIX", "prior_weight": 35, "active": True},
    {"commercial_category_code": "waterproofing", "okpd_pattern": "42.11", "match_type": "PREFIX", "prior_weight": 30, "active": True},
    {"commercial_category_code": "drainage_water_management", "okpd_pattern": "42.11", "match_type": "PREFIX", "prior_weight": 25, "active": True},
    {"commercial_category_code": "curbstone", "okpd_pattern": "42.11", "match_type": "PREFIX", "prior_weight": 20, "active": True},
    {"commercial_category_code": "composite_structures", "okpd_pattern": "42.11", "match_type": "PREFIX", "prior_weight": 20, "active": True},
    {"commercial_category_code": "computers", "okpd_pattern": "26.20", "match_type": "PREFIX", "prior_weight": 80, "active": True},
]

_DEFAULT_ROUTING_SIGNALS = [
    {"commercial_category_code": "lighting", "signal_type": "NEGATIVE_SIGNAL", "phrase": "отопление"},
    {"commercial_category_code": "lighting", "signal_type": "POSITIVE_SIGNAL", "phrase": "светильник"},
    {"commercial_category_code": "lighting", "signal_type": "POSITIVE_SIGNAL", "phrase": "освещение"},
]
