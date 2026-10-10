#!/bin/bash
echo "--- dataset unit ---"
systemctl cat crm-v3-learning-dataset.service 2>/dev/null | grep -E "^ExecStart|^Environment|^EnvironmentFile" | head -8
systemctl cat crm-v3-learning-dataset.timer 2>/dev/null | grep -E "OnCalendar|Persistent|RandomizedDelay" | head -6
echo "--- observer unit ---"
systemctl cat crm-v3-learning-observer.service 2>/dev/null | grep -E "^ExecStart|^Environment=" | head -6
echo "--- last dataset run ---"
journalctl -u crm-v3-learning-dataset.service --no-pager 2>/dev/null | tail -15
echo "--- dataset output files ---"
ls -lt /opt/CRM_Streamlit/var 2>/dev/null | head -10
ls -lt /tmp/*learning* /tmp/*dataset* 2>/dev/null | head -10
