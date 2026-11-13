"""Operational INITIAL_PASS priority signal (not an admission gate).

When CRM_V3_INITIAL_PASS_MODE=1, the signal determines research priority only:

  * authority admission_state = ELIGIBLE (BUSINESS_RESEARCH_ADMISSION_V2)
  * AND a strong commercial signal:
      A. matched commercial OKPD prior, OR
      B. already-saved existing evidence (CURRENT opportunity), OR
      C. WORKS_WITH_EMBEDDED_PRODUCTS / DESIGN_PROJECT contour with a
         design-ish procurement form.

Business admission remains ``BUSINESS_RESEARCH_ADMISSION_V2``. Eligible work
without a prior/evidence/design signal is still selectable at LOW priority.
Reasons are operational scheduling metadata, never business truth.
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

SELECT_NO_PRIORITY_SIGNAL = "INITIAL_NO_PRIORITY_SIGNAL"
# Backward-compatible alias for reports that still use the old label.
SKIP_NO_SIGNAL = SELECT_NO_PRIORITY_SIGNAL
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
    """Return (research_allowed, priority_signal_reason)."""
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
    return True, SELECT_NO_PRIORITY_SIGNAL
