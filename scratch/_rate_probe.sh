#!/bin/bash
URL="https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid=019FF9C532DD74B8B7ABDA527BED6837"
for i in 1 2 3 4 5; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$URL")
  echo "attempt $i: http=$code"
  sleep 10
done
echo "--- after 30s pause ---"
sleep 30
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$URL")
echo "after pause: http=$code"
