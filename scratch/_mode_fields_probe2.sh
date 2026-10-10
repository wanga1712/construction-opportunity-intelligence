#!/bin/bash
PSQL="sudo -n -u postgres psql -d crm -Atc"
echo "--- pid 459631 opportunity ---"
$PSQL "select id, commercial_category_code, commercial_subcategory_code, opportunity_track, procurement_form, analysis_mode, source_contour, commercial_state, status from crm_procurement_category_opportunities where procurement_id=459631"
echo "--- distributions ---"
for col in procurement_form analysis_mode source_contour opportunity_track status; do
  echo "-- $col"
  $PSQL "select coalesce($col::text,'(null)'), count(*) from crm_procurement_category_opportunities group by 1 order by 2 desc limit 6"
done
echo "--- how many procurements have each form ---"
$PSQL "select procurement_form, count(distinct procurement_id) from crm_procurement_category_opportunities group by 1 order by 2 desc limit 8"
echo "--- other tables with mode-ish data ---"
$PSQL "select table_name from information_schema.tables where table_schema='public' and (table_name like '%commercial%' or table_name like '%scope%' or table_name like '%routing%') order by 1"
