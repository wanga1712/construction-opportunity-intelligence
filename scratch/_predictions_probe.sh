#!/bin/bash
PSQL="sudo -n -u postgres psql -d crm -Atc"
echo "--- таблицы с prediction ---"
$PSQL "select table_name from information_schema.tables where table_schema='public' and table_name like '%prediction%'"
echo "--- счётчики ---"
for t in $($PSQL "select table_name from information_schema.tables where table_schema='public' and table_name like '%prediction%'"); do
  printf "%-38s %s\n" "$t" "$($PSQL "select count(*) from $t")"
done
echo "--- кто пишет predictions ---"
cd /opt/CRM_Streamlit && grep -rl "prediction" --include=*.py src/services/commercial_routing_v3 | head -6
