#!/bin/bash
cd /opt/CRM_Streamlit
echo "--- card has new row ---"
grep -c "Срок поставки (док.)" src/ui/procurement_card_page.py
echo "--- restart web app ---"
sudo -n systemctl restart crm-streamlit
sleep 4
systemctl is-active crm-streamlit
curl -s -o /dev/null -w "http=%{http_code}\n" http://127.0.0.1:8504/
