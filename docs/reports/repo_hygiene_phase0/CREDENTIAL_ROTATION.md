# Credential rotation (no secret values)

WIP: `REPO-SECURITY-CREDENTIAL-ROTATION-AND-HISTORY-SANITIZATION-1`  
BASE_HEAD=`cf2b9b3`

## Identity

COMPROMISED_DB_ROLE_IDENTIFIED=YES (`<TENDER_DB_ROLE>` = PostgreSQL role `postgres`)  
COMPROMISED_DB_NAME_IDENTIFIED=YES (`tender_monitor`)  
Historical blob: `dd27873` `deploy/scripts/record_alert.py` (hardcoded connect, no env vars).

The leaked secret was **not** the live S7 password at rotation start. Live consumers already used a different secret. S13 parser `db_credintials.env` still stored the leaked value and new connections with it failed. Live `/usr/local/bin/record_alert.py` still contained the leaked literal.

## Reuse

OLD_PASSWORD_REUSED_ON_S7=NO (current host-local env differed; local connect used the live secret)  
OLD_PASSWORD_REUSED_ON_S13=YES as **stored stale values** in parser env, sibling project env, and `/usr/local/bin/record_alert.py` / `record_metrics.py`  
OLD_PASSWORD_REUSED_BY_OTHER_DB_ROLES=YES as stored strings (`DB_PASSWORD_CATALOG`, `CRM_DB_PASSWORD` in a sibling env). Those strings did **not** authenticate. Role `radar` also stored the leaked string; it was not rotated because connect was not proven live.

ROTATE_THOSE_REUSED_CREDENTIALS_TOO=NO for other live roles. S7 cluster role `postgres` **was** rotated because it is `<TENDER_DB_ROLE>` and remote consumers used it.

## Rotation

NEW_PASSWORD_GENERATED=YES  
NEW_PASSWORD_LENGTH=64  
NEW_PASSWORD_STORAGE_SECURE=YES  
DB_PASSWORD_ROTATED=YES  
ROTATED_DB_ROLE=`<TENDER_DB_ROLE>`  
ROTATION_TIMESTAMP=2026-08-17T18:58:56Z  

S7_CONSUMERS_PRESTAGED=YES  
S13_CONSUMERS_PRESTAGED=YES  
ENV_BACKUPS_CREATED=YES (host-local `*.bak-security-20260817T18582*Z`)  
NEW_PASSWORD_IN_GIT=NO  

S7_NEW_PASSWORD_DB_CONNECT=PASS  
S13_NEW_PASSWORD_DB_CONNECT=PASS  
S7_DB_TARGET_CORRECT=YES  
S13_BACKWARD_TARGETS_S7_DB=YES  
OLD_PASSWORD_NEW_CONNECTION_REJECTED=YES (leaked backup + previous-live CRM backup both FAIL)

## Services

OLD_FORWARD_PID=3717828 NEW_FORWARD_PID=3823514  
FORWARD_SOURCE_DATE=2026-08-17 preserved  
FORWARD_ACTIVE=active  

OLD_BACKWARD_PID=1304055 NEW_BACKWARD_PID=2445032  
BACKWARD_SOURCE_DATE=2026-08-11 preserved  
BACKWARD_ACTIVE=active  

CRM streamlit restarted; Qwen/docs remained inactive.  
Alert scripts on S13 replaced with env-only copies; `temp_shutdown_guard.sh` sources `/etc/tender-monitor-alert.env`.

TEMP_SECRET_FILES_REMOVED=YES  
NEW_SECRET_PRESENT_ONLY_IN_RUNTIME_SECRET_STORES=YES  

NEW_PASSWORD_PRINTED=NO  
NEW_PASSWORD_COMMITTED=NO  
OLD_PASSWORD_PRINTED=NO  
QWEN_STARTED=NO  
DOCUMENT_WORKERS_STARTED=NO  
MODEL_TRAINING_STARTED=NO
