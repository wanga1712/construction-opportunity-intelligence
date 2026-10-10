#!/bin/bash
URL="https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid=019FF9C532DD74B8B7ABDA527BED6837"
echo "--- HEAD ---"
curl -s -D - -o /dev/null --max-time 30 "$URL" | head -15
echo "--- first bytes ---"
curl -s --max-time 30 "$URL" | head -c 300 | tr -d '\0'
echo
echo "--- size ---"
curl -s --max-time 30 "$URL" | wc -c
echo "--- same via S7 (nyx) reachability ---"
timeout 20 curl -s -o /dev/null -w "s13 http=%{http_code} t=%{time_total}\n" --max-time 18 "$URL"
echo "--- env proxy keys used by workers ---"
sudo -n grep -hE "^(PREFER_STUNNEL_PROXY|BYPASS_PROXY|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|USE_PROXY|PROXY_)" /etc/tender-docs-worker-open.env /etc/tender-docs-db.env 2>/dev/null | sed -E 's/(PASSWORD|TOKEN)=.*/\1=***/'
