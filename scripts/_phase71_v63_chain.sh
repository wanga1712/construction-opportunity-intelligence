#!/bin/bash
set -e
cd /opt/CRM_Streamlit
export PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89
export PHASE71_ARMS=v6_3
export PHASE71_OUT=/tmp/phase71_v63_cal.json
export PHASE71_CORPUS=/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json
/opt/CRM_Streamlit/.venv313/bin/python /tmp/_phase71_abc_shadow.py > /tmp/phase71_v63_cal.log 2>&1
export PHASE71_OUT=/tmp/phase71_v63_holdout.json
export PHASE71_CORPUS=/tmp/MODEL_CATEGORY_HOLDOUT_CORPUS.json
/opt/CRM_Streamlit/.venv313/bin/python /tmp/_phase71_abc_shadow.py > /tmp/phase71_v63_holdout.log 2>&1
echo CHAIN_DONE >> /tmp/phase71_v63_chain.log
