"""PostgreSQL-backed taxonomy repository using real database schema."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.models.taxonomy_rules import (
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_PENDING,
    PROPOSAL_STATUS_REJECTED,
    TaxonomyAuditLogDTO,
    TaxonomyProposalDTO,
    TaxonomyRuleDTO,
)


class PostgresTaxonomyRepository:
    """PostgreSQL-backed taxonomy repository using real database schema."""

    def __init__(self, connection_factory: Any) -> None:
        self._connection_factory = connection_factory

    def get_all_rules(self, active_only: bool = True) -> List[TaxonomyRuleDTO]:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                sql = "SELECT rule_id, okpd_pattern, rule_mode, adjustment_weight, reason, created_by, created_at, is_active FROM research_taxonomy_rules"
                if active_only:
                    sql += " WHERE is_active = TRUE"
                sql += " ORDER BY length(okpd_pattern) DESC, okpd_pattern"
                cur.execute(sql)
                rows = cur.fetchall()
                return [
                    TaxonomyRuleDTO(
                        rule_id=r[0],
                        okpd_pattern=r[1],
                        rule_mode=r[2],
                        adjustment_weight=float(r[3]),
                        reason=r[4],
                        created_by=r[5],
                        created_at=r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]),
                        is_active=bool(r[7]),
                    )
                    for r in rows
                ]
        finally:
            conn.close()

    def get_rule_by_id(self, rule_id: str) -> Optional[TaxonomyRuleDTO]:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT rule_id, okpd_pattern, rule_mode, adjustment_weight, reason, created_by, created_at, is_active FROM research_taxonomy_rules WHERE rule_id = %s",
                    (rule_id,),
                )
                r = cur.fetchone()
                if not r:
                    return None
                return TaxonomyRuleDTO(
                    rule_id=r[0],
                    okpd_pattern=r[1],
                    rule_mode=r[2],
                    adjustment_weight=float(r[3]),
                    reason=r[4],
                    created_by=r[5],
                    created_at=r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]),
                    is_active=bool(r[7]),
                )
        finally:
            conn.close()

    def upsert_rule(self, rule: TaxonomyRuleDTO) -> None:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research_taxonomy_rules (rule_id, okpd_pattern, rule_mode, adjustment_weight, reason, created_by, is_active, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (rule_id) DO UPDATE SET
                        okpd_pattern = EXCLUDED.okpd_pattern,
                        rule_mode = EXCLUDED.rule_mode,
                        adjustment_weight = EXCLUDED.adjustment_weight,
                        reason = EXCLUDED.reason,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW();
                    """,
                    (rule.rule_id, rule.okpd_pattern, rule.rule_mode, rule.adjustment_weight, rule.reason, rule.created_by, rule.is_active),
                )
                conn.commit()
        finally:
            conn.close()

    def archive_rule(self, rule_id: str) -> bool:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE research_taxonomy_rules SET is_active = FALSE, updated_at = NOW() WHERE rule_id = %s",
                    (rule_id,),
                )
                affected = cur.rowcount
                conn.commit()
                return affected > 0
        finally:
            conn.close()

    def delete_rule(self, rule_id: str) -> bool:
        return self.archive_rule(rule_id)

    def get_all_proposals(self, status: Optional[str] = None) -> List[TaxonomyProposalDTO]:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                sql = "SELECT proposal_id, okpd_pattern, proposed_mode, proposed_adjustment, evidence_summary, positive_count, negative_count, sample_pids, status, created_at, reviewed_by, reviewed_at FROM research_taxonomy_proposals"
                params = ()
                if status:
                    sql += " WHERE status = %s"
                    params = (status,)
                sql += " ORDER BY created_at DESC"
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [
                    TaxonomyProposalDTO(
                        proposal_id=r[0],
                        okpd_pattern=r[1],
                        proposed_mode=r[2],
                        proposed_adjustment=float(r[3]),
                        evidence_summary=r[4],
                        positive_count=int(r[5]),
                        negative_count=int(r[6]),
                        sample_pids=list(r[7]) if isinstance(r[7], list) else [],
                        status=r[8],
                        created_at=r[9].isoformat() if hasattr(r[9], "isoformat") else str(r[9]),
                        reviewed_by=r[10],
                        reviewed_at=r[11].isoformat() if r[11] and hasattr(r[11], "isoformat") else (str(r[11]) if r[11] else None),
                    )
                    for r in rows
                ]
        finally:
            conn.close()

    def get_proposal_by_id(self, proposal_id: str) -> Optional[TaxonomyProposalDTO]:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT proposal_id, okpd_pattern, proposed_mode, proposed_adjustment, evidence_summary, positive_count, negative_count, sample_pids, status, created_at, reviewed_by, reviewed_at FROM research_taxonomy_proposals WHERE proposal_id = %s",
                    (proposal_id,),
                )
                r = cur.fetchone()
                if not r:
                    return None
                return TaxonomyProposalDTO(
                    proposal_id=r[0],
                    okpd_pattern=r[1],
                    proposed_mode=r[2],
                    proposed_adjustment=float(r[3]),
                    evidence_summary=r[4],
                    positive_count=int(r[5]),
                    negative_count=int(r[6]),
                    sample_pids=list(r[7]) if isinstance(r[7], list) else [],
                    status=r[8],
                    created_at=r[9].isoformat() if hasattr(r[9], "isoformat") else str(r[9]),
                    reviewed_by=r[10],
                    reviewed_at=r[11].isoformat() if r[11] and hasattr(r[11], "isoformat") else (str(r[11]) if r[11] else None),
                )
        finally:
            conn.close()

    def save_proposal(self, proposal: TaxonomyProposalDTO) -> None:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research_taxonomy_proposals (proposal_id, okpd_pattern, proposed_mode, proposed_adjustment, evidence_summary, positive_count, negative_count, sample_pids, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (proposal_id) DO NOTHING;
                    """,
                    (proposal.proposal_id, proposal.okpd_pattern, proposal.proposed_mode, proposal.proposed_adjustment, proposal.evidence_summary, proposal.positive_count, proposal.negative_count, json.dumps(proposal.sample_pids), proposal.status),
                )
                conn.commit()
        finally:
            conn.close()

    def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        reviewed_by: str,
        reviewed_at: Optional[str] = None,
    ) -> Optional[TaxonomyProposalDTO]:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE research_taxonomy_proposals
                    SET status = %s, reviewed_by = %s, reviewed_at = NOW()
                    WHERE proposal_id = %s
                    RETURNING proposal_id, okpd_pattern, proposed_mode, proposed_adjustment, evidence_summary, positive_count, negative_count, sample_pids, status, created_at, reviewed_by, reviewed_at;
                    """,
                    (status, reviewed_by, proposal_id),
                )
                r = cur.fetchone()
                if not r:
                    return None
                conn.commit()
                return TaxonomyProposalDTO(
                    proposal_id=r[0],
                    okpd_pattern=r[1],
                    proposed_mode=r[2],
                    proposed_adjustment=float(r[3]),
                    evidence_summary=r[4],
                    positive_count=int(r[5]),
                    negative_count=int(r[6]),
                    sample_pids=list(r[7]) if isinstance(r[7], list) else [],
                    status=r[8],
                    created_at=r[9].isoformat() if hasattr(r[9], "isoformat") else str(r[9]),
                    reviewed_by=r[10],
                    reviewed_at=r[11].isoformat() if r[11] and hasattr(r[11], "isoformat") else (str(r[11]) if r[11] else None),
                )
        finally:
            conn.close()

    def approve_proposal_atomic(
        self,
        proposal_id: str,
        rule: TaxonomyRuleDTO,
        audit: TaxonomyAuditLogDTO,
    ) -> Optional[TaxonomyRuleDTO]:
        """Atomically locks proposal, validates PENDING status, upserts rule, writes audit, and commits."""
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM research_taxonomy_proposals WHERE proposal_id = %s FOR UPDATE",
                    (proposal_id,),
                )
                row = cur.fetchone()
                if not row or row[0] != PROPOSAL_STATUS_PENDING:
                    conn.rollback()
                    return None

                cur.execute(
                    "UPDATE research_taxonomy_proposals SET status = %s, reviewed_by = %s, reviewed_at = NOW() WHERE proposal_id = %s",
                    (PROPOSAL_STATUS_APPROVED, audit.actor, proposal_id),
                )

                cur.execute(
                    """
                    INSERT INTO research_taxonomy_rules (rule_id, okpd_pattern, rule_mode, adjustment_weight, reason, created_by, is_active, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (rule_id) DO UPDATE SET
                        okpd_pattern = EXCLUDED.okpd_pattern,
                        rule_mode = EXCLUDED.rule_mode,
                        adjustment_weight = EXCLUDED.adjustment_weight,
                        reason = EXCLUDED.reason,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW();
                    """,
                    (rule.rule_id, rule.okpd_pattern, rule.rule_mode, rule.adjustment_weight, rule.reason, rule.created_by, rule.is_active),
                )

                cur.execute(
                    "INSERT INTO research_taxonomy_audit_log (log_id, rule_id, action, actor, details) VALUES (%s, %s, %s, %s, %s)",
                    (audit.log_id, rule.rule_id, audit.action, audit.actor, audit.details),
                )

                cur.execute(
                    """
                    INSERT INTO research_taxonomy_meta (meta_key, meta_value, updated_at)
                    VALUES ('version', '{"version": 1}'::jsonb, NOW())
                    ON CONFLICT (meta_key) DO UPDATE SET
                        meta_value = jsonb_set(COALESCE(research_taxonomy_meta.meta_value, '{"version": 1}'::jsonb), '{version}', (COALESCE((research_taxonomy_meta.meta_value->>'version')::int, 0) + 1)::text::jsonb),
                        updated_at = NOW();
                    """
                )
                conn.commit()
                return rule
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_audit_log(self, entry: TaxonomyAuditLogDTO) -> None:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO research_taxonomy_audit_log (log_id, rule_id, action, actor, details) VALUES (%s, %s, %s, %s, %s)",
                    (entry.log_id, entry.rule_id, entry.action, entry.actor, entry.details),
                )
                conn.commit()
        finally:
            conn.close()

    def get_audit_logs(self, limit: int = 100) -> List[TaxonomyAuditLogDTO]:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT log_id, rule_id, action, actor, details, created_at FROM research_taxonomy_audit_log ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
                return [
                    TaxonomyAuditLogDTO(
                        log_id=r[0],
                        rule_id=r[1],
                        action=r[2],
                        actor=r[3],
                        details=r[4],
                        timestamp=r[5].isoformat() if hasattr(r[5], "isoformat") else str(r[5]),
                    )
                    for r in rows
                ]
        finally:
            conn.close()

    def get_taxonomy_version(self) -> int:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT meta_value->>'version' FROM research_taxonomy_meta WHERE meta_key = 'version'")
                r = cur.fetchone()
                return int(r[0]) if r and r[0] else 1
        finally:
            conn.close()

    def increment_taxonomy_version(self) -> int:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research_taxonomy_meta (meta_key, meta_value, updated_at)
                    VALUES ('version', '{"version": 1}'::jsonb, NOW())
                    ON CONFLICT (meta_key) DO UPDATE SET
                        meta_value = jsonb_set(COALESCE(research_taxonomy_meta.meta_value, '{"version": 1}'::jsonb), '{version}', (COALESCE((research_taxonomy_meta.meta_value->>'version')::int, 0) + 1)::text::jsonb),
                        updated_at = NOW()
                    RETURNING meta_value->>'version';
                    """
                )
                r = cur.fetchone()
                conn.commit()
                return int(r[0]) if r and r[0] else 1
        finally:
            conn.close()
