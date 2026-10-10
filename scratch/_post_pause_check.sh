#!/bin/bash
PSQL="sudo -n -u postgres psql -d document_intelligence -Atc"
echo "--- units ---"
systemctl list-units "tender-docs-*" --all --no-legend --plain | awk '{print $1, $3, $4}' | head -15
echo "--- processes ---"
pgrep -fa "document_processor.daemon" | head -3 || echo "нет"
echo "--- queue (all statuses) ---"
$PSQL "select status, count(*) from document_processing_queue group by 1 order by 2 desc"
echo "--- our requeue mark ---"
$PSQL "select status, count(*) from document_processing_queue where last_error='requeue:direct_missing_files' group by 1"
echo "--- stuck PROCESSING (any worker) ---"
$PSQL "select count(*) from document_processing_queue where status='PROCESSING'"
echo "--- 429 check ---"
curl -s -o /dev/null -w "http=%{http_code}\n" --max-time 15 "https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid=019FF9C532DD74B8B7ABDA527BED6837"
