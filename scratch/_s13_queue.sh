#!/bin/bash
PSQL="sudo -n -u postgres psql -d"
echo "--- queue(document_intelligence) ---"
$PSQL document_intelligence -Atc "select status, count(*) from document_processing_queue group by status order by count(*) desc"
echo "--- findings last 12h ---"
$PSQL document_intelligence -Atc "select count(*) from document_match_details where created_at > now() - interval '12 hours'"
echo "--- queue last activity ---"
$PSQL document_intelligence -Atc "select max(created_at) from document_processing_queue"
echo "--- verify/invalid totals ---"
$PSQL document_intelligence -Atc "select coalesce(verification_status,'?'), count(*) from document_match_details group by 1 order by 2 desc"
echo "--- units ---"
systemctl list-units 'tender-docs-*' --no-legend --plain | awk '{print $1, $3, $4}'
