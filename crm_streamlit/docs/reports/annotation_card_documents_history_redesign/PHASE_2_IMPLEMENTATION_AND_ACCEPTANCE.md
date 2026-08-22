# Phase 2 — card read model and production UI redesign

Status: **PASS / STOP AFTER PHASE 2**.

## Implementation

Canonical implementation commit: `18bb49dcf1c8f39ee8d860253bf0417bb19b464c`, descended from Phase 1 audit commit `602e2abe28c033f96ed7f4f5bcc8c7914ddf9ad0` and baseline `149e5d9bf25d9164967e5ccd8abba3cade2e18b3`.

`annotation_card_view.py` is the read-only composition boundary for explicit procurement facts, complete S7 resolver inventory, optional stored observations and existing persisted history. The UI no longer treats `crm_v3_document_observations` or the capped canonical summary as the document inventory.

- OPEN primary amount: `initial_price`, label `НМЦК`.
- AWARDED primary amount: factual `final_contract_price` (source `final_price` fallback only on awarded lifecycle), label `Цена контракта`; initial price remains secondary.
- OPEN deadline: procedure/application `end_date`, label `Приём заявок до`.
- AWARDED deadline: execution/delivery end, label `Исполнение до`; no historical bid deadline is presented as actionable.
- Contract action: only strict factual S7 row `Информация о контракте` with `/epz/contract/` URL; provenance includes link table and source document id.
- Documents: complete resolver result with unique-physical collapse and truthful `source_row_count` / `source_document_ids` lineage.
- Observation join: `source_document_id` first. Exact stripped URL is a legacy fallback only for observations without an id. Fuzzy title matching is forbidden. Orphans remain separate.
- States keep `UNOBSERVED`, evidence/no-evidence, download/parse failure, unsupported, empty and duplicate distinctions.

The five logical tabs, MODEL/EXPERT authority boundary, versioned expert payload, document-priority URL identity, SAVE, SAVE & NEXT and OUT OF PROFILE were preserved. History event generation was not changed.

## Verification

Local focused/regression tests: **62 passed**. S13 clean pre-activation worktree, including production entrypoint: **67 passed**. Python compilation and `git diff --check`: PASS. The broader local collection cannot import the external `CRM_SOURCE_ROOT/modules` dependency in this isolated worktree; the corresponding production-entrypoint test passed on S13 with the authoritative host environment.

Tree-identical standalone deployment commit: `7984d22d1fd1b136685192d658ab23ed700ecf3c`. Its tree equals `18bb49d:crm_streamlit`. Deployment used the current runtime commit `fc0d53ae0be8621fb63eae0e43b67a680b709d13` as standalone parent only; histories were not merged. Activation had an explicit automatic rollback path. Final service state: active, HTTP 200, tracked runtime clean.

Read-only production AppTest/read-model acceptance:

| CRM id | Lifecycle/law | Primary amount | Deadline | Raw rows | Visible physical docs | UNOBSERVED | Contract link | Exceptions |
|---:|---|---|---|---:|---:|---:|---|---:|
| 1013 | OPEN / 223-ФЗ | НМЦК 1,400,000 | 2026-12-31 | 2 | 2 | 2 | absent | 0 |
| 8021 | OPEN / 44-ФЗ | НМЦК 4,020,029,027.22 | 2026-08-14 | 256 | 170 | 170 | absent | 0 |
| 17390 | OPEN / 223-ФЗ | НМЦК 175,000 | 2026-12-30 | 6 | 6 | 6 | absent | 0 |
| 20254 | AWARDED / 44-ФЗ | contract 5,675,888.99 | 2026-05-31 | 30 | 2 | 2 | factual | 0 |
| 20256 | AWARDED / 44-ФЗ | contract 331,398,905.55 | 2027-12-31 | 275 | 25 | 25 | factual | 0 |

For every case: title and three prominent metrics rendered; procurement link rendered; contract link matched lifecycle/factual availability; document link count equalled the complete unique-physical inventory; every zero-observation document rendered `Документ ещё не исследован`; five tabs and universally applicable fast actions rendered. Category CORRECT/INCORRECT rendered on cards having model categories and remained absent where no category proposition exists. Reset-filter acceptance passed with zero exceptions and restored all logical/widget defaults.

Production observation count remains zero. Synthetic unit fixtures prove ID join, URL-only legacy join, unmatched orphan isolation, evidence/no-evidence and failure distinctions. `DOCUMENT_JOIN_REAL_OBSERVATION_VALIDATED=PENDING`, as explicitly permitted. Awarded 223-ФЗ real validation also remains pending because no case exists.

No model, prompt, model input, routing, category registry, business rule, normal CRM publication, document worker/download, parser/ingestion, expert storage, source data or DDL changed.
