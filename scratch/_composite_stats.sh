#!/bin/bash
PSQL="sudo -n -u postgres psql -d crm -Atc"
PSQLD="sudo -n -u postgres psql -d document_intelligence -Atc"
echo "--- категория composite_structures ---"
$PSQL "select count(distinct procurement_id) from crm_procurement_category_opportunities where commercial_category_code='composite_structures'"
echo "--- из них с документами и находками ---"
$PSQLD "with cat as (select distinct procurement_id from crm_procurement_category_opportunities where commercial_category_code='composite_structures') select 1" 2>/dev/null
$PSQLD "select count(*) from (select procurement_id from document_files where download_status='COMPLETED' and local_deleted_at is null group by 1) t"
echo "--- топ закупок категории по числу находок ---"
$PSQLD "select procurement_id, count(*) from document_match_details group by 1 order by 2 desc limit 10"
