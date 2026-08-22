# Exact deploy acceptance

Status: **EXACT DEPLOY ACTIVE; FINAL ACCEPTANCE ITERATION IN PROGRESS**.

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

## Final iteration still pending

- Publish/redeploy the exact procurement-link caption alignment and read-only fresh-filter/reset acceptance script.
- Re-run final SHA parity and production acceptance.

Current proof: `GIT_DEPLOYED_RUNTIME_PARITY=YES`, `SERVICE_RESTARTED=YES`, `RUNNING_TREE_PARITY=YES`; final reconciliation result remains pending until the caption/reset acceptance iteration is deployed and rechecked.
