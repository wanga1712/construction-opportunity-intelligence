# WIP_ELIGIBLE_NO_SIGNAL_MUST_STILL_RESEARCH_V1

## Goal

Make canonical `admission_state=ELIGIBLE` sufficient for document-research
reachability. Initial commercial signal controls priority only.

## Invariants

```text
BUSINESS_RESEARCH_ADMISSION_V2 is the only business admission authority.
ELIGIBLE + initial signal -> HIGH priority.
ELIGIBLE + no initial signal -> LOW/NORMAL priority.
Both priorities use the existing document queue.
No category opportunity is created before parsed/normalized evidence.
Existing documents and estimate rows are reused.
```

## Scope

Routing selector, queue admission, daily document reconciliation, document
queue planning, kiosk daily labels and focused regression checks.

No taxonomy, medal, confirmed-base, category-value or dossier changes.

## Status

`PASS_WITH_HISTORICAL_BACKLOG (2026-11-13)`

## Result

```text
NO_SIGNAL_STOP_CONDITION_FOUND=YES
NO_SIGNAL_STOP_CONDITION_REMOVED=YES
BUSINESS_ADMISSION_AUTHORITY=BUSINESS_RESEARCH_ADMISSION_V2
QUEUE_AUTHORITY=crm_procurement_scope_authority + Queue V2

ELIGIBLE_WITH_SIGNAL_PRIORITY=HIGH
ELIGIBLE_WITHOUT_SIGNAL_PRIORITY=LOW

TODAY_RECEIVED=38
TODAY_WITH_SIGNAL=17
TODAY_WITHOUT_SIGNAL=21

TODAY_21_RESEARCHABLE=21
TODAY_21_QUEUED=21
TODAY_21_ALREADY_FURTHER=0
TODAY_21_UNACCOUNTED=0

END_TO_END_CANARY_CARDS=5
END_TO_END_MATCHED=1
END_TO_END_ZERO_MATCH=4
CANARY_FULL_NORMALIZATION_COMPLETED=5/5

HISTORICAL_ELIGIBLE_NO_SIGNAL=19795
HISTORICAL_CURRENT=6914
HISTORICAL_RECOVERY_QUEUED=21
HISTORICAL_NEVER_RESEARCHED_CURRENT_REMAINING=6893

KIOSK_UPDATED=YES
SYNTHETIC_CATEGORY_OPPORTUNITIES=0
```

At release completion, the 21-card document queue had `15 COMPLETED`,
`6 PROCESSING`, `0 FAILED`; all 21 had selected documents. The five-card
normalization canary used PID `485026` as `MATCHED` and
`485024/485027/485028/485031` as zero-match with complete row coverage.

The remaining historical current/no-signal/research-missing cohort is a bounded
recovery backlog, not a routing blocker. It was not mass-queued in this WIP.

```text
TESTS=30 passed
DEPLOYED=YES
BLOCKERS=NONE
NEXT_WIP=WIP_HISTORICAL_ELIGIBLE_NO_SIGNAL_BOUNDED_RECOVERY_V1
```
