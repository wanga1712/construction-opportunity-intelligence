# Exact deploy acceptance

Status: **PRE-DEPLOY GATES COMPLETE; DEPLOY NOT YET PERFORMED**.

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

## Deployment gates still pending

- Commit audit/report updates and push reconciliation branch to canonical GitHub.
- Deploy one exact Git-derived tree (not individual source copies), preserving only excluded host configuration/secrets.
- Full post-deploy application-source SHA256 parity with zero mismatches.
- Approved service restart and running-process/tree proof.
- Fresh served-app acceptance for РАЗМЕТКА counts/reset, procurement link, fast annotation actions, normal publication gate, model authority, documents/history version, and data freshness.

Until those gates pass: `GIT_DEPLOYED_RUNTIME_PARITY=NO`, `SERVICE_RESTARTED=NO`, `RUNNING_TREE_PARITY=NO`, and final reconciliation result is not PASS.
