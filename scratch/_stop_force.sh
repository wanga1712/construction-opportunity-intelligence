#!/bin/bash
echo "--- stop stuck force unit ---"
sudo -n systemctl stop run-u3357249.service 2>/dev/null || echo "(unit already gone)"
echo "--- reset its queue row (must not stay PROCESSING) ---"
sudo -n -u postgres psql -d document_intelligence -Atc \
  "update document_processing_queue set status='PENDING', worker_id=null, started_at=null, last_error='requeue:direct_missing_files' where worker_id=77 returning id, procurement_id, status"
echo "--- requeue mark state ---"
sudo -n -u postgres psql -d document_intelligence -Atc \
  "select status, count(*) from document_processing_queue where last_error='requeue:direct_missing_files' group by 1 order by 2 desc"
echo "--- rate check now ---"
curl -s -o /dev/null -w "http=%{http_code}\n" --max-time 20 \
  "https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid=019FF9C532DD74B8B7ABDA527BED6837"
