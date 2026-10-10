#!/bin/bash
PSQL="sudo -n -u postgres psql -d crm -Atc"
echo "--- crm_v3_learning_examples ---"
$PSQL "select count(*) from crm_v3_learning_examples"
$PSQL "select coalesce(producer_version,'(null)'), coalesce(dataset_split,'(null)'), coalesce(label_source,'(null)'), count(*) from crm_v3_learning_examples group by 1,2,3 order by 4 desc limit 10"
echo "--- columns ---"
$PSQL "select column_name||' '||data_type from information_schema.columns where table_name='crm_v3_learning_examples' order by ordinal_position"
echo "--- кто пишет в таблицу (в коде) ---"
cd /opt/CRM_Streamlit && grep -rl "crm_v3_learning_examples" --include=*.py src scripts 2>/dev/null | head -10
echo "--- observer last output ---"
journalctl -u crm-v3-learning-observer.service --no-pager 2>/dev/null | grep -vE "Starting|Stopping|Stopped|Deactivated|Consumed" | tail -8
