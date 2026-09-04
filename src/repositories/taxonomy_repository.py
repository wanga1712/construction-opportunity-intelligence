"""Repository for superuser research taxonomy rules, proposals, and audit logs."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional

from src.models.taxonomy_rules import (
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_PENDING,
    PROPOSAL_STATUS_REJECTED,
    TaxonomyAuditLogDTO,
    TaxonomyProposalDTO,
    TaxonomyRuleDTO,
)


DEFAULT_TAXONOMY_STORAGE_PATH = "data/taxonomy/research_taxonomy.json"


class TaxonomyRepository:
    """Thread-safe storage for research taxonomy rules, proposals, and audit logs."""

    def __init__(self, storage_path: Optional[str] = DEFAULT_TAXONOMY_STORAGE_PATH) -> None:
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._rules: Dict[str, TaxonomyRuleDTO] = {}
        self._proposals: Dict[str, TaxonomyProposalDTO] = {}
        self._audit_logs: List[TaxonomyAuditLogDTO] = []
        self._load()

    def _load(self) -> None:
        """Loads repository state from storage file if available."""
        if not self.storage_path or not os.path.exists(self.storage_path):
            return

        with self._lock:
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                self._rules = {
                    r["rule_id"]: TaxonomyRuleDTO.from_dict(r)
                    for r in data.get("rules", [])
                }
                self._proposals = {
                    p["proposal_id"]: TaxonomyProposalDTO.from_dict(p)
                    for p in data.get("proposals", [])
                }
                self._audit_logs = [
                    TaxonomyAuditLogDTO.from_dict(a)
                    for a in data.get("audit_logs", [])
                ]
            except Exception:
                pass

    def _save(self) -> None:
        """Persists current state to storage file if configured."""
        if not self.storage_path:
            return

        os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
        payload = {
            "rules": [r.to_dict() for r in self._rules.values()],
            "proposals": [p.to_dict() for p in self._proposals.values()],
            "audit_logs": [a.to_dict() for a in self._audit_logs],
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def get_all_rules(self, active_only: bool = True) -> List[TaxonomyRuleDTO]:
        """Returns all rules, optionally filtering active only."""
        with self._lock:
            rules = list(self._rules.values())
            if active_only:
                rules = [r for r in rules if r.is_active]
            return sorted(rules, key=lambda x: (len(x.okpd_pattern), x.okpd_pattern), reverse=True)

    def get_rule_by_id(self, rule_id: str) -> Optional[TaxonomyRuleDTO]:
        """Retrieves rule by id."""
        with self._lock:
            return self._rules.get(rule_id)

    def upsert_rule(self, rule: TaxonomyRuleDTO) -> None:
        """Inserts or updates a rule and persists state."""
        with self._lock:
            self._rules[rule.rule_id] = rule
            self._save()

    def delete_rule(self, rule_id: str) -> bool:
        """Deletes a rule by id."""
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]
                self._save()
                return True
            return False

    def get_all_proposals(self, status: Optional[str] = None) -> List[TaxonomyProposalDTO]:
        """Returns proposals, optionally filtered by status."""
        with self._lock:
            proposals = list(self._proposals.values())
            if status:
                proposals = [p for p in proposals if p.status == status]
            return sorted(proposals, key=lambda x: x.created_at, reverse=True)

    def save_proposal(self, proposal: TaxonomyProposalDTO) -> None:
        """Saves a proposal."""
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal
            self._save()

    def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        reviewed_by: str,
        reviewed_at: Optional[str] = None,
    ) -> Optional[TaxonomyProposalDTO]:
        """Updates proposal status and reviewer."""
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return None
            from datetime import datetime, timezone
            proposal.status = status
            proposal.reviewed_by = reviewed_by
            proposal.reviewed_at = reviewed_at or datetime.now(timezone.utc).isoformat()
            self._save()
            return proposal

    def add_audit_log(self, entry: TaxonomyAuditLogDTO) -> None:
        """Appends an entry to the audit log."""
        with self._lock:
            self._audit_logs.append(entry)
            self._save()

    def get_audit_logs(self, limit: int = 100) -> List[TaxonomyAuditLogDTO]:
        """Returns the most recent audit logs."""
        with self._lock:
            return sorted(self._audit_logs, key=lambda x: x.timestamp, reverse=True)[:limit]
