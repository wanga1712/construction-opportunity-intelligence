# PRODUCTION_DEPLOY

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

S13_PRODUCTION_DEPLOYED=NO

Git port is ready. Live S13 `/opt/tendermonitor` was **not** changed. Backward service was **not** restarted in this session.

Do not deploy until the isolated Git-code replay of `/tmp/eis_s13_parity/rgk` plus notice identity comparison is executed without production writes.

Required at deploy time (not done):

- backup only files that will change → `BACKUP_PATH_ALIAS=<BACKWARD_RUNTIME_BACKUP>`
- restart **only** `tendermonitor-eis-parser-backward.service`
- preserve `BACKWARD_SOURCE_DATE=2026-08-11` and region_progress
- IMPORT_ERRORS=0 DB_ERRORS=0 FK_ERRORS=0 BATCH_ERRORS=0 UNHANDLED_EXCEPTIONS=0
