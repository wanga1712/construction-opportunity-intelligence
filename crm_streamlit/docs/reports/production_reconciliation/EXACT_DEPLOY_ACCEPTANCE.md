# Exact deploy acceptance

Status: **PASS — EXACT GIT / S13 / DB RECONCILIATION COMPLETE**.

## Authority and pre-change proof

- Canonical GitHub heads were fetched and verified: main `cc3ebc6aade727e479ed876a4fbef38881e238e5`, annotation `0eac40b6d190b0b7d23a681e6948625c3164b88c`, model authority `a7f2c8a3ace26cb2d3c09fb07fc90c626862ca6a`.
- S13 pre-change runtime: HEAD `580cc9f52067864bf3eec836dc1a30d5e93a4b06`, branch `queue-policy-v2-admin-ui-20260806`, dirty (48 tracked modified files and 227 untracked entries).
- Sanitized forensic snapshot: logical S13 path `/var/lib/crm-v3-canary/production_reconciliation/prechange_20260822_202200`; application archive, runtime-history bundle, Git status/diffs, service metadata, migration inventory and SHA256 manifest are present.
- Actual service is active and uses the approved S13 CRM workdir, `.venv313` Streamlit entrypoint and the same code tree shown by the running PID. Environment-file contents were not copied or reported.

## Reconciliation decision

- Base: canonical annotation WIP `0eac40b6d190b0b7d23a681e6948625c3164b88c`.
- Imported desired runtime delta: existing commit `20cb2e8b7cdcb906156c0660b7e27f0617822c20`, resolved into reconciliation commit `725fd00`.
- Imported application files: annotation queue, annotation workbench, annotation card, annotation-card provenance and extracted annotation-card sections; associated tests/report were retained.
- Excluded: concrete host/operator values, access-path comments, misplaced temp/test artifacts and Phase 10 SHADOW ref-transport/model-validation files.
- Model, prompt, publication rules and document-processing daemon behavior are unchanged by the candidate tree.

## Off-runtime validation

- Focused pytest: **95 passed in 6.53s** (annotation workbench/queue/expert UI, publication visibility, production entrypoint, model UI authority boundary, document-lane authority and refresh/cache).
- Static syntax: **372 Python files parsed successfully**.
- Repository checks: `git diff --check` passed; no unknown drift classification remains.
- Schema: required production objects match; no DDL required.

## First exact-deploy proof

- Reconciliation GitHub head: `ac24800867f01c92b3128b27201a487230439ab9`.
- Tree-identical standalone deployment commit: `e69ce418ea23558b532ebfea50b22ebc91b90034`; its tree ID equals `ac24800:crm_streamlit`.
- Clean S13 checkout activated atomically; prior dirty tree retained as a recoverable backup.
- Service restarted active, expected workdir/entrypoint/PID, localhost HTTP 200.
- Independent `git archive` closure comparison: 335 tracked runtime files matched, zero application-source mismatches; only documented host-local `.streamlit/config.toml` was additional.
- Real-production read-only AppTest: five tabs, procurement source link, source/model/business/expert boundaries, factual history, legacy warning and all fast-annotation actions passed with zero exceptions.

## Operator-relevant runtime acceptance

- Fresh РАЗМЕТКА: `TOTAL_OPEN_ASSESSED=64`, `CURRENT_FILTER_RESULT=64`, publication visibility defaults to ALL.
- Reset: PASS; logical filter object and all five Streamlit widget keys return to `open_assessed / unannotated / all / all / all`.
- Procurement link: exact caption `Открыть закупку` visible for real procurement 1013.
- Fast annotation: CORRECT, INCORRECT, add-missing-category, OUT-OF-PROFILE and SAVE & NEXT controls visible.
- Card: five expected tabs, factual documents empty-state, real history, legacy warning and model/business/expert authority boundaries pass with zero exceptions.
- Normal CRM publication behavior: unchanged; focused publication tests pass.
- Data freshness: latest source timestamp `2026-08-22 20:42:13.907172+03`, latest CRM row update `2026-08-22 20:44:23.435193+03`, latest assessment `2026-08-20 14:22:02.8924+03`. The visible `2026-08-12` is a historical assessment version on the accepted procurement, not a current sync cutoff.

Final proof: `GIT_DEPLOYED_RUNTIME_PARITY=YES`, `FILES_MISMATCHED=0`, `SERVICE_RESTARTED=YES`, `RUNNING_TREE_PARITY=YES`, `RECONCILIATION_RESULT=PASS`. Exact final commit hashes are reported externally because a commit cannot contain its own hash.
