"""Operational INITIAL_PASS gate (separate from canonical production eligibility).

When CRM_V3_INITIAL_PASS_MODE=1, the canonical selector keeps its semantics but
Qwen admission is narrowed to the real commercial cohort:

  * authority admission_state = ELIGIBLE (BUSINESS_RESEARCH_ADMISSION_V2)
  * AND a strong commercial signal:
      A. matched commercial OKPD prior, OR
      B. already-saved existing evidence (CURRENT opportunity), OR
      C. WORKS_WITH_EMBEDDED_PRODUCTS / DESIGN_PROJECT contour with a
         design-ish procurement form.

Fail-closed when authority is missing. Reasons are OPERATIONAL (initial-pass
scheduling), never persisted as business truth.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

ADMISSION_POLICY_VERSION = "BUSINESS_RESEARCH_ADMISSION_V2"
SCOPE_WORKS = "WORKS_WITH_EMBEDDED_PRODUCTS"
SCOPE_DESIGN = "DESIGN_PROJECT"
SCOPE_DIRECT_GOODS = "DIRECT_GOODS"

SELECT_OKPD = "INITIAL_OKPD_PRIOR"
SELECT_EVIDENCE = "INITIAL_EXISTING_EVIDENCE"
SELECT_DESIGN_WORKS = "INITIAL_DESIGN_WORKS_PRIOR"

SKIP_NO_SIGNAL = "INITIAL_NO_COMMERCIAL_SIGNAL"
SKIP_NOT_ELIGIBLE = "INITIAL_ADMISSION_NOT_ELIGIBLE"
SKIP_AWARDED_DIRECT = "INITIAL_AWARDED_DIRECT_GOODS"

DESIGN_FORMS = frozenset({
    "DESIGN_ONLY",
    "SURVEY_AND_DESIGN",
    "DESIGN_AND_BUILD",
    "DESIGN_EXPERTISE_AND_BUILD",
})


def initial_pass_mode() -> bool:
    return os.getenv("CRM_V3_INITIAL_PASS_MODE", "0").strip().lower() in ("1", "true", "yes", "on")


def initial_pass_decision(
    authority: Optional[Dict[str, Any]],
    has_prior: bool,
    has_existing_evidence: bool,
    designish: bool,
) -> Tuple[bool, Optional[str]]:
    """Return (select, reason). Always select when initial-pass mode is off."""
    if not initial_pass_mode():
        return True, None

    if not authority:
        return False, SKIP_NOT_ELIGIBLE

    lc = str(authority.get("source_lifecycle") or "").upper()
    scope = str(authority.get("procurement_scope_type") or "").upper()
    admitted = (
        authority.get("admission_state") == "ELIGIBLE"
        and authority.get("admission_policy_version") == ADMISSION_POLICY_VERSION
    )
    if not admitted:
        if lc == "AWARDED" and scope == SCOPE_DIRECT_GOODS:
            return False, SKIP_AWARDED_DIRECT
        return False, SKIP_NOT_ELIGIBLE

    if has_prior:
        return True, SELECT_OKPD
    if has_existing_evidence:
        return True, SELECT_EVIDENCE
    if scope in (SCOPE_WORKS, SCOPE_DESIGN) and designish:
        return True, SELECT_DESIGN_WORKS
    return False, SKIP_NO_SIGNAL
