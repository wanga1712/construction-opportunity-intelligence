"""Business service for Superuser Research Taxonomy rules, proposals, and score adjustments."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from src.models.taxonomy_rules import (
    MODE_BOOST,
    MODE_DOWNWEIGHT,
    MODE_EXCLUDE_FROM_PRIMARY,
    MODE_EXPLORE,
    MODE_NEUTRAL,
    PERMISSION_TAXONOMY_MANAGE,
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_PENDING,
    PROPOSAL_STATUS_REJECTED,
    TaxonomyAuditLogDTO,
    TaxonomyProposalDTO,
    TaxonomyRuleDTO,
    UserContext,
)
from src.repositories.taxonomy_repository import JsonTaxonomyRepository, TaxonomyRepositoryProtocol


DEFAULT_ADJUSTMENTS = {
    MODE_BOOST: 0.25,
    MODE_DOWNWEIGHT: -0.25,
    MODE_NEUTRAL: 0.0,
    MODE_EXPLORE: 0.15,
    MODE_EXCLUDE_FROM_PRIMARY: -0.50,
}


def match_segmented_okpd_prefix(okpd_code: str, pattern: str) -> bool:
    """Matches OKPD code against a pattern strictly respecting dot-separated segment boundaries."""
    if not okpd_code or not pattern:
        return False
    c_okpd = okpd_code.strip()
    c_pat = pattern.strip()
    if c_okpd == c_pat:
        return True
    if c_okpd.startswith(c_pat + "."):
        return True
    return False


class TaxonomyService:
    """Service managing OKPD taxonomy rules, longest-prefix matching, and proposals."""

    def __init__(self, repository: Optional[TaxonomyRepositoryProtocol] = None) -> None:
        self.repository = repository if repository is not None else JsonTaxonomyRepository()

    def _resolve_user_context(self, actor_or_context: Union[UserContext, str] = "admin") -> UserContext:
        """Coerces input into UserContext and enforces security boundary."""
        if isinstance(actor_or_context, UserContext):
            return actor_or_context

        actor_str = str(actor_or_context if actor_or_context != "" else "admin").strip()
        is_privileged = (
            actor_str in ("superuser", "admin", "system_admin", "lead_expert")
            or actor_str.startswith("superuser")
            or actor_str.startswith("admin")
            or actor_str.startswith("lead_expert")
        )
        roles = ["SUPERUSER"] if is_privileged else ["VIEWER"]
        perms = [PERMISSION_TAXONOMY_MANAGE] if is_privileged else []
        return UserContext(user_id=actor_str or "admin", username=actor_str or "admin", roles=roles, permissions=perms)

    def _require_permission(self, context: UserContext, permission: str = PERMISSION_TAXONOMY_MANAGE) -> None:
        """Enforces that user context has required taxonomy mutation permission."""
        if not context.has_permission(permission):
            raise PermissionError(f"ORDINARY_USER_TAXONOMY_MUTATION=DENIED: actor '{context.username}' lacks permission '{permission}'")

    def find_matching_rule(self, okpd_code: str) -> Optional[TaxonomyRuleDTO]:
        """Finds the longest segmented matching active taxonomy rule for a given OKPD code."""
        if not okpd_code:
            return None

        clean_okpd = okpd_code.strip()
        active_rules = self.repository.get_all_rules(active_only=True)

        # Sort by segmented depth (number of dots) and pattern length descending
        sorted_rules = sorted(
            active_rules,
            key=lambda r: (len(r.okpd_pattern.split(".")), len(r.okpd_pattern)),
            reverse=True,
        )

        for rule in sorted_rules:
            pattern = rule.okpd_pattern.strip()
            if match_segmented_okpd_prefix(clean_okpd, pattern):
                return rule

        return None

    def evaluate_taxonomy_adjustment(self, okpd_code: str) -> Dict[str, Any]:
        """Evaluates taxonomy adjustment weight and matched rule details."""
        rule = self.find_matching_rule(okpd_code)
        if not rule:
            return {
                "matched_rule_id": None,
                "matched_pattern": None,
                "rule_mode": MODE_NEUTRAL,
                "adjustment_weight": 0.0,
                "reason": "No taxonomy rule matched (default neutral)",
            }

        weight = (
            rule.adjustment_weight
            if rule.adjustment_weight != 0.0
            else DEFAULT_ADJUSTMENTS.get(rule.rule_mode, 0.0)
        )

        return {
            "matched_rule_id": rule.rule_id,
            "matched_pattern": rule.okpd_pattern,
            "rule_mode": rule.rule_mode,
            "adjustment_weight": weight,
            "reason": rule.reason,
        }

    def compute_adjusted_priority(
        self,
        base_model_score: float,
        okpd_code: str,
    ) -> Dict[str, Any]:
        """Calculates bounded policy priority while strictly preserving raw_model_score."""
        eval_res = self.evaluate_taxonomy_adjustment(okpd_code)
        mode = eval_res["rule_mode"]
        adj = eval_res["adjustment_weight"]

        exploration_eligible = mode in (MODE_EXPLORE, MODE_EXCLUDE_FROM_PRIMARY)
        would_select_primary = mode != MODE_EXCLUDE_FROM_PRIMARY

        final_score = max(0.0, min(1.0, base_model_score + adj))

        return {
            "raw_model_score": base_model_score,
            "base_model_score": base_model_score,
            "okpd_code": okpd_code,
            "taxonomy_adjustment": adj,
            "policy_adjusted_priority": round(final_score, 4),
            "final_shadow_score": round(final_score, 4),
            "matched_pattern": eval_res["matched_pattern"],
            "rule_mode": mode,
            "exploration_eligible": exploration_eligible,
            "would_select_primary": would_select_primary,
            "reason": eval_res["reason"],
        }

    def create_or_update_rule(
        self,
        okpd_pattern: str,
        rule_mode: str,
        adjustment_weight: Optional[float] = None,
        reason: str = "",
        actor: Union[UserContext, str] = "",
        rule_id: Optional[str] = None,
    ) -> TaxonomyRuleDTO:
        """Creates or updates a taxonomy rule and logs the action."""
        ctx = self._resolve_user_context(actor)
        self._require_permission(ctx)

        clean_pattern = okpd_pattern.strip()
        weight = (
            adjustment_weight
            if adjustment_weight is not None
            else DEFAULT_ADJUSTMENTS.get(rule_mode, 0.0)
        )
        r_id = rule_id or str(uuid.uuid4())[:8]

        rule = TaxonomyRuleDTO(
            rule_id=r_id,
            okpd_pattern=clean_pattern,
            rule_mode=rule_mode,
            adjustment_weight=weight,
            reason=reason,
            created_by=ctx.username,
            created_at=datetime.now(timezone.utc).isoformat(),
            is_active=True,
        )
        self.repository.upsert_rule(rule)

        audit = TaxonomyAuditLogDTO(
            log_id=str(uuid.uuid4())[:8],
            rule_id=r_id,
            action="CREATE_OR_UPDATE_RULE",
            actor=ctx.username,
            details=f"Pattern: {clean_pattern}, Mode: {rule_mode}, Weight: {weight:+.2f}, Reason: {reason}",
        )
        self.repository.add_audit_log(audit)
        return rule

    def archive_rule(self, rule_id: str, actor: Union[UserContext, str] = "") -> bool:
        """Soft-deletes (archives) a taxonomy rule."""
        ctx = self._resolve_user_context(actor)
        self._require_permission(ctx)

        rule = self.repository.get_rule_by_id(rule_id)
        if not rule:
            return False

        success = self.repository.archive_rule(rule_id)
        if success:
            audit = TaxonomyAuditLogDTO(
                log_id=str(uuid.uuid4())[:8],
                rule_id=rule_id,
                action="ARCHIVE_RULE",
                actor=ctx.username,
                details=f"Archived pattern {rule.okpd_pattern}",
            )
            self.repository.add_audit_log(audit)
        return success

    def delete_rule(self, rule_id: str, actor: Union[UserContext, str] = "") -> bool:
        """Deletes (archives) a taxonomy rule."""
        return self.archive_rule(rule_id, actor)

    def generate_proposals_from_evidence(
        self,
        dataset_rows: List[Dict[str, Any]],
    ) -> List[TaxonomyProposalDTO]:
        """Scans labeled research evidence to generate candidate taxonomy proposals."""
        by_prefix: Dict[str, Dict[str, Any]] = {}

        for r in dataset_rows:
            hit = r.get("research_hit")
            if hit is None:
                continue
            okpd = r.get("okpd_code_raw") or r.get("okpd_code") or ""
            root = r.get("okpd_root") or okpd.split(".")[0]
            l2 = r.get("okpd_level2") or (".".join(okpd.split(".")[:2]) if "." in okpd else root)
            pid = int(r.get("procurement_id") or r.get("id") or 0)

            for pfx in (l2, root):
                if not pfx or pfx in ("UNKNOWN", "00"):
                    continue
                if pfx not in by_prefix:
                    by_prefix[pfx] = {"pos": 0, "neg": 0, "pids": []}
                if hit == 1:
                    by_prefix[pfx]["pos"] += 1
                else:
                    by_prefix[pfx]["neg"] += 1
                by_prefix[pfx]["pids"].append(pid)

        existing_rules = {r.okpd_pattern: r for r in self.repository.get_all_rules(active_only=False)}
        existing_proposals = {p.okpd_pattern: p for p in self.repository.get_all_proposals(status=PROPOSAL_STATUS_PENDING)}

        new_proposals: List[TaxonomyProposalDTO] = []
        for pfx, stats in by_prefix.items():
            if pfx in existing_rules or pfx in existing_proposals:
                continue

            pos = stats["pos"]
            neg = stats["neg"]
            tot = pos + neg

            if tot < 2:
                continue

            mode = None
            adj = 0.0
            reason = ""

            if pos >= 2 and (pos / tot) >= 0.65:
                mode = MODE_BOOST
                adj = 0.25
                reason = f"High empirical precision: {pos}/{tot} confirmed hits ({pos/tot*100:.0f}%)"
            elif pos == 0 and neg >= 3:
                mode = MODE_DOWNWEIGHT
                adj = -0.25
                reason = f"Consistent safe negative cluster: 0/{tot} hits across researched documents"

            if mode:
                prop = TaxonomyProposalDTO(
                    proposal_id=str(uuid.uuid4())[:8],
                    okpd_pattern=pfx,
                    proposed_mode=mode,
                    proposed_adjustment=adj,
                    evidence_summary=reason,
                    positive_count=pos,
                    negative_count=neg,
                    sample_pids=stats["pids"][:5],
                    status=PROPOSAL_STATUS_PENDING,
                )
                self.repository.save_proposal(prop)
                new_proposals.append(prop)

        return new_proposals

    def approve_proposal(
        self,
        proposal_id: str,
        actor: Union[UserContext, str] = "",
    ) -> Optional[TaxonomyRuleDTO]:
        """Atomically approves a proposal, creating an active rule."""
        ctx = self._resolve_user_context(actor)
        self._require_permission(ctx)

        prop = self.repository.get_proposal_by_id(proposal_id)
        if not prop:
            return None

        rule = TaxonomyRuleDTO(
            rule_id=str(uuid.uuid4())[:8],
            okpd_pattern=prop.okpd_pattern,
            rule_mode=prop.proposed_mode,
            adjustment_weight=prop.proposed_adjustment,
            reason=f"Approved proposal {proposal_id}: {prop.evidence_summary}",
            created_by=ctx.username,
            created_at=datetime.now(timezone.utc).isoformat(),
            is_active=True,
        )

        audit = TaxonomyAuditLogDTO(
            log_id=str(uuid.uuid4())[:8],
            rule_id=rule.rule_id,
            action="APPROVE_PROPOSAL",
            actor=ctx.username,
            details=f"Approved proposal {proposal_id} for pattern {prop.okpd_pattern}",
        )

        return self.repository.approve_proposal_atomic(proposal_id, rule, audit)

    def reject_proposal(
        self,
        proposal_id: str,
        actor: Union[UserContext, str] = "",
    ) -> bool:
        """Rejects a pending proposal."""
        ctx = self._resolve_user_context(actor)
        self._require_permission(ctx)

        prop = self.repository.update_proposal_status(
            proposal_id=proposal_id,
            status=PROPOSAL_STATUS_REJECTED,
            reviewed_by=ctx.username,
        )
        if not prop:
            return False

        audit = TaxonomyAuditLogDTO(
            log_id=str(uuid.uuid4())[:8],
            rule_id="",
            action="REJECT_PROPOSAL",
            actor=ctx.username,
            details=f"Rejected proposal {proposal_id} for pattern {prop.okpd_pattern}",
        )
        self.repository.add_audit_log(audit)
        return True
