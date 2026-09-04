"""Thread-safe JSON and in-memory repository implementation for Research Taxonomy."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional
import uuid

from src.models.taxonomy_rules import (
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_PENDING,
    PROPOSAL_STATUS_REJECTED,
    TaxonomyAuditLogDTO,
    TaxonomyProposalDTO,
    TaxonomyRuleDTO,
)
from src.repositories.taxonomy_base import DEFAULT_TAXONOMY_STORAGE_PATH


class JsonTaxonomyRepository:
    """Thread-safe JSON / memory implementation for offline and testing environments."""

    def __init__(self, storage_path: Optional[str] = DEFAULT_TAXONOMY_STORAGE_PATH) -> None:
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._rules: Dict[str, TaxonomyRuleDTO] = {}
        self._proposals: Dict[str, TaxonomyProposalDTO] = {}
        self._audit_logs: List[TaxonomyAuditLogDTO] = []
        self._version: int = 1
        self._load()

    def _load(self) -> None:
        if not self.storage_path or not os.path.exists(self.storage_path):
            return
        with self._lock:
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._rules = {r["rule_id"]: TaxonomyRuleDTO.from_dict(r) for r in data.get("rules", [])}
                self._proposals = {p["proposal_id"]: TaxonomyProposalDTO.from_dict(p) for p in data.get("proposals", [])}
                self._audit_logs = [TaxonomyAuditLogDTO.from_dict(a) for a in data.get("audit_logs", [])]
                self._version = int(data.get("version", 1))
            except Exception:
                pass

    def _save(self) -> None:
        if not self.storage_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
        payload = {
            "version": self._version,
            "rules": [r.to_dict() for r in self._rules.values()],
            "proposals": [p.to_dict() for p in self._proposals.values()],
            "audit_logs": [a.to_dict() for a in self._audit_logs],
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def get_all_rules(self, active_only: bool = True) -> List[TaxonomyRuleDTO]:
        with self._lock:
            rules = list(self._rules.values())
            if active_only:
                rules = [r for r in rules if r.is_active]
            return sorted(rules, key=lambda x: (len(x.okpd_pattern), x.okpd_pattern), reverse=True)

    def get_rule_by_id(self, rule_id: str) -> Optional[TaxonomyRuleDTO]:
        with self._lock:
            return self._rules.get(rule_id)

    def upsert_rule(self, rule: TaxonomyRuleDTO) -> None:
        with self._lock:
            self._rules[rule.rule_id] = rule
            self._save()

    def archive_rule(self, rule_id: str) -> bool:
        with self._lock:
            rule = self._rules.get(rule_id)
            if not rule:
                return False
            rule.is_active = False
            self._save()
            return True

    def delete_rule(self, rule_id: str) -> bool:
        return self.archive_rule(rule_id)

    def get_all_proposals(self, status: Optional[str] = None) -> List[TaxonomyProposalDTO]:
        with self._lock:
            props = list(self._proposals.values())
            if status:
                props = [p for p in props if p.status == status]
            return sorted(props, key=lambda x: x.positive_count, reverse=True)

    def get_proposal_by_id(self, proposal_id: str) -> Optional[TaxonomyProposalDTO]:
        with self._lock:
            return self._proposals.get(proposal_id)

    def save_proposal(self, proposal: TaxonomyProposalDTO) -> None:
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
        with self._lock:
            prop = self._proposals.get(proposal_id)
            if not prop:
                return None
            prop.status = status
            prop.reviewed_by = reviewed_by
            if reviewed_at:
                prop.reviewed_at = reviewed_at
            self._save()
            return prop

    def approve_proposal_atomic(
        self,
        proposal_id: str,
        rule: TaxonomyRuleDTO,
        audit: TaxonomyAuditLogDTO,
    ) -> Optional[TaxonomyRuleDTO]:
        with self._lock:
            prop = self._proposals.get(proposal_id)
            if not prop:
                return None
            prop.status = PROPOSAL_STATUS_APPROVED
            prop.reviewed_by = rule.created_by
            self._rules[rule.rule_id] = rule
            self._audit_logs.append(audit)
            self._version += 1
            self._save()
            return rule

    def add_audit_log(self, entry: TaxonomyAuditLogDTO) -> None:
        with self._lock:
            self._audit_logs.append(entry)
            self._save()

    def get_audit_logs(self, limit: int = 100) -> List[TaxonomyAuditLogDTO]:
        with self._lock:
            return sorted(self._audit_logs, key=lambda x: x.timestamp, reverse=True)[:limit]

    def get_taxonomy_version(self) -> int:
        with self._lock:
            return self._version

    def increment_taxonomy_version(self) -> int:
        with self._lock:
            self._version += 1
            self._save()
            return self._version
