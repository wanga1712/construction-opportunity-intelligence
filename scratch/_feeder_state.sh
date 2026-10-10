#!/bin/bash
echo "--- units ---"
systemctl list-units 'crm-v3-factual*' --all --no-legend --plain 2>/dev/null | head -5
systemctl is-enabled crm-v3-factual-feeder.service 2>/dev/null; systemctl is-active crm-v3-factual-feeder.service 2>/dev/null
echo "--- unit config ---"
systemctl cat crm-v3-factual-feeder.service 2>/dev/null | grep -E "^Environment|^ExecStart|^EnvironmentFile" | head -12
echo "--- last runs ---"
journalctl -u crm-v3-factual-feeder.service --since "24 hours ago" --no-pager 2>/dev/null | grep -iE "candidates|admitted|queue|cycle|error" | tail -12
echo "--- queue feeder env values ---"
grep -h "FEED_BATCH_SIZE" /etc/tender-docs*.env /opt/CRM_Streamlit/.env 2>/dev/null | head -5
