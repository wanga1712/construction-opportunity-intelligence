# CRM V3 Launch Roadmap

This document outlines the roadmap for restoring performance, stabilizing queue operations, executing factual research, extracting structured facts and project metadata, and launching the autonomous learning loop for CRM V3.

---

## Project Stages

### R0: UI RESTORE / FREEZE
- **Status**: `ACCEPTED / COMPLETE`
- **Details**: Analytics UI restored to accepted S13 production baseline commit `f5285b6dade45a21df5b055fb7048835090de24a`. UI code is frozen to prevent regressions.

---

### R1: RUNTIME + GIT AUDIT
- **Status**: `ACCEPTED / COMPLETE`
- **Details**: Authoritative runtime state audit, verification of uncommitted changes, git state synchronization, and mapping of pipeline file authorities completed.

---

### R2: 223-FZ DATE RECONCILIATION
- **Status**: `ACCEPTED / COMPLETE`
- **Details**: Date reconciliation completed. Recovered legacy 223-FZ application deadlines, resolved unrecoverable legacy canaries, added PostgreSQL check constraints, and verified sync functionality.

---

### R3: EXHAUSTIVE FACTUAL RESEARCH
- **Status**: `ACCEPTED / COMPLETE`
- **Details**:
  - Exhaustive factual research pipeline established (`pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'`).
  - ContextValidator V4 quality holdout passed (`context_validator / v4 / QWEN_CONTEXT_V4`).
  - Infrastructure and model execution failures (`MODEL_EXCEPTION`, `INVALID_JSON`, `JSON_PARSE_ERROR`, `INVALID_DECISION_ENUM`) are nonterminal (`is_retryable = True`).
  - Sequential candidate batch validation breaks immediately on first technical failure to prevent candidate queue starvation.
  - Bounded exponential backoff implemented in daemon main loop (`60s -> 120s -> 240s -> 480s -> 900s max`).
  - Exactly 260 timeout-terminalized rows recovered to claimable state with zero evidence corruption.
  - Post-recovery real systemd daemon batch proof passed (`POST_RECOVERY_REAL_DAEMON_BATCH = PASS`).
  - Production service (`crm-v3-context-validator.service`) is healthy, active, and processing target backlog safely.

---

### R4: STRUCTURED PRODUCT / FACT NORMALIZATION
- **Status**: `CURRENT`

#### R4 Substage Progress & Roadmap:

- **R4-A: Structured Fact Contract & Storage**
  - **Status**: `COMPLETE`
  - **Details**: Trusted V4 input detail binding, pure documentary source snapshot, field-level provenance, raw-value quote matching, fail-closed numeric/unit/currency normalization, and idempotent storage.

- **R4-B: Raw-First Structured Fact Extractor V1**
  - **Status**: `COMPLETE`
  - **Details**: Qwen raw documentary fact extractor V1 (`qwen2.5:7b`, prompt `structured_fact_v1`) implemented and verified via development smoke.

- **R4-C: Fresh Promotion-Quality Extraction Evaluation**
  - **Status**: `WAITING_FOR_FRESH_HOLDOUT`
  - **Details**: `STRUCTURED_EXTRACTOR_V1_QUALITY_GATE = NOT_EVALUATED`. Promotion-quality extractor evaluation requires fresh, model-unexposed V4 `CONFIRMED` details. The five canonical development `CONFIRMED` details (`38319`, `38324`, `38325`, `38373`, `38417`) are development-exposed and blacklisted from promotion evaluation. Awaiting accumulation of fresh `CONFIRMED` rows from the active R3 validator daemon.

- **R4-D: Structured Extractor Production Service Bounded Proof**
  - **Status**: `TODO`
  - **Details**: Production service deployment and bounded execution proof of `StructuredFactExtractor`, to be executed after R4-C quality gate passes.

- **R4-PD: PROJECT DOCUMENTATION METADATA (MANDATORY)**
  - **Status**: `TODO / MANDATORY BEFORE R5`
  - **Details**:
    - **Trigger**: When procurement documents contain project documentation, the system must process the project-documentation set as a separate structured metadata source, in addition to product/material/work extraction. Project-document metadata must not be represented as product entities.
    - **Project Document Set & Open Section Vocabulary**: Project documentation contains multi-discipline section files (e.g. ЭОМ, ЭО, ЭС, АР, КР, КЖ, КМ, ВК, НВК, ОВ, ОВиК, СС, ТХ, etc.). Vocabulary is open (`CLOSED_SECTION_VOCABULARY = NO`). Store raw section code/name exactly as documented.
    - **Thematic Section Relation**: Product/material/work facts remain associated with their specific thematic section where found (e.g. lighting -> electrical section, flooring -> architectural section). Project-document organization and person metadata is collected across the **whole available project documentation set**, not limited to the target commercial product section.
    - **Project Organizations**: Extract every explicitly stated project/design organization across available project documentation. Fields include `organization_name_raw`, `organization_role_raw` (nullable), `section_code_raw`, `section_name_raw`, `document_name`, `archive_member_path`, `page_or_sheet`, and `source_quote`. Do not infer organization identity from external knowledge.
    - **Project People**: Extract all explicitly stated people associated with project documentation. Fields include `person_name_raw`, `role_raw`, `organization_name_raw` (nullable), `section_code_raw`, `section_name_raw`, `document_name`, `archive_member_path`, `page_or_sheet`, and `source_quote`.
    - **Open Role Vocabulary**: `CLOSED_ROLE_VOCABULARY = NO`. Role vocabulary must remain open. Non-exhaustive signal examples include: ГИП, ГАП, генеральный директор, директор, главный инженер, главный специалист, начальник отдела, руководитель группы, руководитель проекта, разработал, выполнил, проверил, согласовал, нормоконтроль, and unseen role wording.
    - **Name Forms**: Preserve `person_name_raw` exactly as documented (full surname/name/patronymic, surname + initials, initials + surname, signature-block text). Optional parsed fields (`surname`, `given_name`, `patronymic`, `initials`) may be provided as auxiliary attributes but may not replace the raw form.
    - **Associations**: Role↔person and Organization↔person associations require explicit documentary evidence (same title-block row, signature row, explicit text phrase, table row). Proximity on page does not imply association. Do not assume all participants belong to the first organization found.
    - **Occurrence-Level Provenance**: `PROJECT_METADATA_WITHOUT_SOURCE_QUOTE = INVALID`. Every occurrence preserves document identity, section, page/sheet, and exact source quote.
    - **Deduplication Rule**: Raw occurrences survive deduplication (`RAW OCCURRENCES -> optional normalized/deduplicated view`). Evidence is never discarded.
    - **Sole Factual Authority**: Sole authority is project files. No outside knowledge (internet, external company databases).
    - **Separate Domain Model**: Project organizations and people are NOT `StructuredEntity(PRODUCT/MATERIAL/EQUIPMENT)`. They require a dedicated project-document metadata domain model and storage layer.
    - **Future Downstream Purpose**: Future CRM object/procurement cards may expose project institutes, ГИП/ГАП, section authors, and participants to enable filtering by project organization, role, or section. UI implementation remains R9 / later work.

---

### R5: LEARNING TARGET COMPLETION
- **Status**: `TODO`
- **Details**: Implement all required target tasks (e.g. document relevance, categories, commercial medals) in the learning example builder.

---

### R6: DATASET VALIDATION / TRAIN-VALIDATION-HOLDOUT
- **Status**: `TODO`
- **Details**: Validate target datasets and verify correct distribution and isolation of training, validation, and holdout splits.

---

### R7: FINE-TUNE / HOLDOUT / PROMOTION
- **Status**: `TODO`
- **Details**: Create model fine-tuning loops and implement strict evaluation gating using holdout datasets before promotion.

---

### R8: GOLD/SILVER HUNTER PRIORITY
- **Status**: `TODO`
- **Details**: Implement priority queueing logic utilizing Qwen blind predictions to process high-value opportunities first.

---

### R9: HOURLY METRICS + CRM FILTERS + READ-ONLY RESULTS
- **Status**: `TODO`
- **Details**: Develop dashboard widgets/scripts tracking real-time queue states, and safely re-introduce read-only filters for research status and structured findings.

---

### R10: 24H PRODUCTION SLA RUN
- **Status**: `TODO`
- **Details**: Run the complete automated pipeline for a full 24-hour cycle under production load with zero failures.
