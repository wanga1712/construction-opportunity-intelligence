#!/bin/bash
set -e
ENV_FILE=/opt/tender_documents_research/.env
echo "--- backup + set 60 min backoff ---"
cp -n "$ENV_FILE" "$ENV_FILE.bak_429_$(date +%Y%m%dT%H%M%S)" 2>/dev/null || true
sed -i -E '/^HTTP_429_(BACKOFF_SECONDS|MAX_SLEEP|RETRIES)=/d' "$ENV_FILE"
{
  echo "HTTP_429_BACKOFF_SECONDS=3600"
  echo "HTTP_429_MAX_SLEEP=3600"
  echo "HTTP_429_RETRIES=0"
} >> "$ENV_FILE"
tail -4 "$ENV_FILE"
echo "--- stop all document workers ---"
sudo -n systemctl stop "tender-docs-daemon-open" "tender-docs-daemon-open-2" "tender-docs-daemon-open-3" \
  "tender-docs-daemon-awarded" "tender-docs-daemon-awarded-2" "tender-docs-daemon-computers" \
  "tender-docs-band-gold-1" "tender-docs-band-gold-2" "tender-docs-band-silver" \
  "tender-docs-band-bronze" "tender-docs-band-wood" 2>/dev/null || true
sleep 3
echo "--- state ---"
systemctl list-units "tender-docs-*" --no-legend --plain | awk '{print $1, $3, $4}'
echo "--- worker processes left ---"
pgrep -fa "document_processor.daemon" | head -5 || echo "нет процессов"
