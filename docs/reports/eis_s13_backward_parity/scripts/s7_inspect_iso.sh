#!/bin/bash
set -euo pipefail
echo HOST=S7
echo RGK_XML_COUNT=$(find /tmp/eis_s13_parity/rgk -maxdepth 1 -name '*.xml' | wc -l)
sudo -n -u postgres psql -d tender_monitor -v ON_ERROR_STOP=1 -At <<'SQL'
SELECT 'FILE_NAMES_COLS=' || string_agg(column_name, ',' ORDER BY ordinal_position)
FROM information_schema.columns
WHERE table_name = 'file_names_xml';
SELECT 'FK=' || conrelid::regclass::text || '>' || confrelid::regclass::text
FROM pg_constraint
WHERE contype = 'f'
  AND conrelid::regclass::text IN (
    'reestr_contract_44_fz',
    'reestr_contract_44_fz_commission_work',
    'reestr_contract_44_fz_unknown',
    'reestr_contract_44_fz_unclear',
    'reestr_contract_44_fz_awarded',
    'reestr_contract_44_fz_completed',
    'rgk_contract_unresolved',
    'links_documentation_44_fz',
    'file_names_xml'
  );
SQL
echo LIVE_RGK_BATCH=$(test -f /opt/tendermonitor/parsing_xml/rgk_batch.py && echo YES || echo NO)
echo OLD_PREPLACED=$(test -f /tmp/eis_s13_parity_old/parsing_xml/okpd_parser.py && echo YES || echo NO)
echo GIT_BATCH=$(test -f /tmp/eis_s13_parity_git/eis_ingestion/s13_backfill/parsing_xml/rgk_batch.py && echo YES || echo NO)
