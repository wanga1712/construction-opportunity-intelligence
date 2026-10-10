#!/bin/bash
PSQL="sudo -n -u postgres psql -d document_intelligence -Atc"
echo "--- download_attempts columns ---"
$PSQL "select column_name||' '||data_type from information_schema.columns where table_name='download_attempts' order by ordinal_position"
echo "--- recent attempts ---"
$PSQL "select left(row_to_json(t)::text, 300) from download_attempts t order by id desc limit 5"
echo "--- recent FAILED reasons ---"
$PSQL "select left(coalesce(error_message,''),70), count(*) from document_files where download_status='FAILED' and created_at > now() - interval '2 hours' group by 1 order by 2 desc limit 8"
echo "--- direct curl test to zakupki.gov.ru ---"
curl -s -o /dev/null -w "http=%{http_code} time=%{time_total}\n" --max-time 25 "https://zakupki.gov.ru/epz/order/notice/printForm/view.html?regNumber=0351100008926000151" || echo "curl failed rc=$?"
echo "--- wg/amnezia status ---"
systemctl is-active amneziawg-worker.service 2>/dev/null; ip -brief addr show 2>/dev/null | head -8
