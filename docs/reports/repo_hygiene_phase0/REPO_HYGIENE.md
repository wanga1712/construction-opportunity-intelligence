# Phase 0 — repository hygiene

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

This report lists paths and categories only. It does not contain host
addresses, credentials, key material, or `.env` values.

## 0.1 Current tree scan (after sanitization)

REPO_HYGIENE_FINDINGS=

- HEAD worktree no longer contains known S7/S13 VPN address literals,
  the extra VPN-style DB host literal, SSH `user@host` targets, identity
  filenames, or personal Windows/Linux home prefixes.
- Runtime DB/SSH targets now come from env (`TENDER_MONITOR_DB_HOST` /
  `DB_HOST*` / `S7_SSH_*` / `S13_SSH_*` / `S7_EIS_GATEWAY_HOST`).
- systemd gateway unit uses `EnvironmentFile` plus `${S7_EIS_GATEWAY_HOST}`.
- Committed env templates use `<S7_DB_HOST>` and `${DB_PASSWORD}`.
- Localhost `127.0.0.1` and bind address `0.0.0.0` remain as generic values.
- Public GitHub repository URL is unchanged.

FILES_WITH_INFRA_DETAILS= (sanitized in this WIP; categories)

- docs / reports: README, EIS inventory/deploy/validation/DB route,
  correctness side-redownload, year-long audit source history,
  architecture daemon reconciliation, CRM operating rules and related
  CRM docs, tender_documents_research README and archive docs
- templates: `deploy/env_templates/*`
- systemd: `deploy/systemd/*`, `eis_ingestion/systemd/*`
- SQL comments: CRM migrations
- runtime: CRM infrastructure/health/document DB helpers, EIS and
  document `database_connection.py` SSL host special-case

FILES_WITH_POSSIBLE_SECRETS=

- history blob `deploy/scripts/record_alert.py` at commit `dd27873`
  (hardcoded DB password assignment). Current HEAD of that file reads
  `TENDER_MONITOR_DB_PASSWORD` from env only.
- tracked `db_credintials.env.example` files are empty placeholders.
- no PEM/OpenSSH private-key headers or WireGuard private-key assignments in HEAD.

## 0.2 Git history scan

INFRA_DETAILS_IN_HISTORY=YES

Known S7/S13 address literals, SSH login names, and identity filenames
appear in published reachable history (including `github/main` and the
already-pushed WIP branch). Removing them from HEAD does not remove them
from Git history.

CREDENTIALS_IN_HISTORY=YES

One reachable commit contains a real password assignment:

- `dd27873` `deploy/scripts/record_alert.py`
- ancestor of current HEAD and of `github/main`

PRIVATE_KEYS_IN_HISTORY=NO

Zero commits contain PEM/OpenSSH/RSA/EC/DSA/PGP private-key headers
or WireGuard private-key assignments.

## 0.3 Current-file sanitization

DONE for tracked docs/templates/systemd/runtime that still had literals.

Logical aliases in Git: S7, S13, S7_DB, FORWARD_RUNTIME, BACKWARD_RUNTIME.
Placeholders: `<S7_DB_HOST>`, `<SSH_USER>`, `<S7_SSH_USER>`,
`<S13_SSH_USER>`, `<SSH_IDENTITY>`, `<HOME>`.

Generic unit names and `/opt/tendermonitor` kept.

## 0.4 History cleanup

STOPPED. Do not run `git-filter-repo` until the leaked DB password is
rotated. History rewrite would delete the blob from Git but would not
invalidate the already-published credential.

Required before rewrite:

1. Rotate the `tender_monitor` password that was hardcoded in
   `deploy/scripts/record_alert.py` at `dd27873`.
2. Rotate any reuse of that secret (same value in host env files).
3. Confirm no other credential blobs remain (re-run path-only scanner).
4. Local `--mirror` backup, then `git-filter-repo --replace-text` from
   untracked `.hygiene/replace-text.txt`.
5. Re-scan reachable refs until
   `REAL_SERVER_ADDRESSES_IN_REACHABLE_HISTORY=0` and
   `SECRETS_IN_REACHABLE_HISTORY=0`.
6. Push only after hygiene PASS, using `--force-with-lease`, not blind
   `--force`. Then clone remote into a clean temp directory and rescan.

HISTORY_REWRITE=NOT_STARTED
PUSH=NOT_DONE (still forbidden for `cf2b9b3`; rewrite would change that SHA)

## 0.5 Future protection

ADDED:

- `tools/repo_hygiene_check.py` — generic secret patterns plus optional
  untracked denylist (no production hosts hardcoded in the checker)
- `tools/repo_hygiene_denylist.example` — RFC 5737 documentation IPs only
- `.gitignore` — `.env`, `db_credintials.env`, `*.pem` / `*.key` / VPN
  material, `.hygiene/`

GitHub noreply: documented in `crm_streamlit/docs/PROJECT_OPERATING_RULES.md`.
Local `git config` was not changed.

## 0.6 Remote rescan

REMOTE_INFRA_LITERAL_SCAN=NOT_RUN
REMOTE_SECRET_SCAN=NOT_RUN

Push is blocked until password rotation + history rewrite + local hygiene
PASS. After that, clone the canonical GitHub remote into a temp directory
and run `python tools/repo_hygiene_check.py` with a local denylist.
