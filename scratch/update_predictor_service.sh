#!/bin/bash
cat << 'EOF' > /tmp/crm-v3-shadow-predictor.service
[Unit]
Description=CRM V3 Shadow Predictor Daemon
After=network.target postgresql.service

[Service]
Type=simple
User=sergey
WorkingDirectory=/opt/CRM_Streamlit_rescue
Environment=PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/etc/crm_v3.env
ExecStart=/opt/CRM_Streamlit/.venv313/bin/python -m src.services.commercial_routing_v3.shadow_predictor
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo mv /tmp/crm-v3-shadow-predictor.service /etc/systemd/system/crm-v3-shadow-predictor.service
sudo systemctl daemon-reload
sudo systemctl restart crm-v3-shadow-predictor.service
echo "SHADOW_PREDICTOR_SERVICE_UPDATED_AND_RESTARTED"
