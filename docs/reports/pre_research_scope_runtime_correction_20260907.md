# Pre-Research Runtime Correction

Date: 2026-09-07  
WIP: `CRM-V3-PRE-RESEARCH-SCOPE-CLASSIFICATION-AND-LIVE-ADMISSION-MATERIALIZATION-1`

## P0 Document Credentials

`CommercialRoutingV3QueueProducer` now builds the document DSN from:

- database: `document_intelligence`
- user source: `S13_DOCUMENT_DB_USER`
- password source: `S13_DOCUMENT_DB_PASSWORD`

There is no CRM credential fallback in the document DSN builder. CRM credentials remain limited to CRM connections.

## P1 DWRR Runtime Boundary

The worker-safe implementation is `tender_documents_research/document_processor/dwrr_claim_policy.py`. S13 worker queue repositories no longer import `src.services.dwrr_claim_policy`.

- `DWRR_IMPORT_WITHOUT_SRC=PASS`
- `DWRR_SYNTHETIC_SELECTION=PASS`
- `DOCUMENT_WORKER_SRC_IMPORT_REQUIRED=NO`
- Local bounded assertions: `17 PASS`
- `compileall`: PASS

## P2-P4 Admission Safety

- Active queue reconciliation compares only `PENDING`/`PRE_RESEARCH_WAITING` rows with current CRM scope authority.
- Reconciliation updates only admission metadata/context; completed and failed history is excluded.
- Missing authority becomes `HOLD`; state transitions such as `ELIGIBLE -> EXCLUDED`, `ELIGIBLE -> HOLD`, and re-eligibility are represented by the same idempotent reconciliation function.
- `MAX_ADMISSION_STALENESS_BEFORE_CLAIM` is explicitly `reconciled immediately before every claim cycle`.
- Claim SQL requires `ELIGIBLE`, `BUSINESS_RESEARCH_ADMISSION_V1`, and non-null admission evaluation provenance.
- OPEN admitted rows use `open_active`; AWARDED admitted rows use the existing `awarded_recent` lane.
- Admission remains before lane priority and DWRR/GOLD overlay.

## P6 Research Dedup Precedence

Canonical research identity is now `(normalized_source_family, normalized_notice_number)`, with `procurement_id` used only when no notice number exists. Audited supported registry variants normalize to `44_FZ` or `223_FZ`; unsupported legacy variants fail closed. The producer checks all generations and lifecycle table variants, not only `S13_V4_EXHAUSTIVE_CONTEXT`, and applies this precedence:

- `PROCESSING` or pending identity: do not enqueue a duplicate.
- successful `COMPLETED`: reuse the existing research row; do not download or parse again.
- `FAILED` or `PARTIAL`: retry the existing canonical identity rather than inserting a second job.
- `NO_LINKS`: do not retry until current canonical links exist; then retry the same identity.
- Old `COMPLETED` rows without successful result evidence are interpreted as `PARTIAL` during lookup, not as a normal terminal state.
- lifecycle changes, including OPEN -> AWARDED, retain the same identity and existing research attachment.

The canonical identity key is persisted in `category_context` for traceability. Lookup prefers that key and falls back to a normalized SQL projection for legacy rows, so it does not require the current lifecycle `source_table`. Check-plus-insert is protected by a PostgreSQL transaction advisory lock on the canonical key. Local direct assertions cover 44-FZ and 223-FZ lifecycle identity, status precedence, `NO_LINKS`, and the absence of generation-only dedup.

## P5 S13 Deployment Boundary

Read-only S13 audit:

- Runtime path: `/opt/tender_documents_research`
- Runtime Git root: `/opt/CRM_Streamlit`
- Runtime HEAD: `b83c46c518819a849903bde2cad5ea911ce131bc`
- Runtime branch: `CRM-V3-CATEGORY-OPPORTUNITY-CARDS-AND-MULTI-MEDAL-OUTPUT-1`
- Worker cwd: `/opt/tender_documents_research`
- Worker Python: `/opt/tender_documents_research/.venv/bin/python`
- Units use project/system environment files; values were not printed.
- Current relevant worker units are already active; no restart or release was performed.

The runtime path resolves into a dirty parent checkout on an older branch, not the canonical current HEAD. Changing that parent checkout could affect other services, and no separately approved deployment route to the worker directory is documented.

`DEPLOYMENT_SOURCE_PROVEN=NO`  
`SAFE_DEPLOYMENT_ROUTE=NOT_PROVEN`

Therefore actual S13 import smoke is intentionally not claimed. Migration 007, authority materialization, queue reconciliation writes, claim dry-run, downloads, and worker release were not performed.

`READY_FOR_V4_WORKER_RESTORE=NO`.
