#!/bin/bash
PSQL="sudo -n -u postgres psql -d document_intelligence -Atc"
echo "--- tables ---"
$PSQL "select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by 1"
echo "--- rowcounts (top 20 by est rows) ---"
$PSQL "select relname, n_live_tup from pg_stat_user_tables where schemaname='public' order by n_live_tup desc limit 20"
