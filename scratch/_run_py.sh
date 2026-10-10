#!/bin/bash
# Wrapper: run a python script inside /opt/CRM_Streamlit with production env.
# usage: bash /tmp/_run_py.sh /tmp/script.py [args...]
set -a
. /opt/CRM_Streamlit/.env
set +a
cd /opt/CRM_Streamlit
export PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89
exec .venv313/bin/python "$@"
