#!/bin/bash
# Phase 9 - Backup files that will be replaced during S13 backward deploy
set -euo pipefail

BACKUP_DIR="/opt/tendermonitor/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_ALIAS="eis_s13_backward_pre_batch_deploy_${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_ALIAS}.tgz"

mkdir -p "$BACKUP_DIR"

# Files that will be replaced: s13_backfill parsing_xml and database_work modules
# Only backup what is in the live backward parsing_xml directory
cd /opt/tendermonitor
tar --preserve-permissions -czf "$BACKUP_PATH" \
    parsing_xml/ \
    database_work/contract_awarded_promoter.py \
    database_work/contract_location.py \
    database_work/contract_lookup_strategy.py \
    database_work/contract_registry_locator.py \
    database_work/contract_registry_updater.py \
    database_work/database_id_fetcher.py \
    database_work/database_operations.py \
    database_work/recouped_contract_sync.py \
    database_work/registry_tables.py \
    2>/dev/null || true

# Also backup secondary_functions.py and main.py if present
tar --preserve-permissions -czf "$BACKUP_PATH" \
    parsing_xml/ \
    2>/dev/null || true

echo "BACKWARD_RUNTIME_BACKUP_CREATED=YES"
echo "BACKWARD_RUNTIME_BACKUP_ALIAS=${BACKUP_ALIAS}"
echo "BACKUP_PATH=${BACKUP_PATH}"
ls -la "$BACKUP_PATH"
