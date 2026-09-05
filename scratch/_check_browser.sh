#!/bin/bash
set -eu

echo "=== CHECK BROWSER AUTOMATION TOOLS ==="
# Check if any browser automation is available
/opt/CRM_Streamlit/.venv313/bin/python -c "
try:
    import playwright; print('PLAYWRIGHT=YES')
except: print('PLAYWRIGHT=NO')
try:
    import selenium; print('SELENIUM=YES')
except: print('SELENIUM=NO')
try:
    from streamlit.testing.v1 import AppTest; print('STREAMLIT_APPTEST=YES')
except: print('STREAMLIT_APPTEST=NO')
"

# Check if chromium/chrome is installed
which chromium 2>/dev/null && echo "CHROMIUM=YES" || echo "CHROMIUM=NO"
which google-chrome 2>/dev/null && echo "CHROME=YES" || echo "CHROME=NO"
which firefox 2>/dev/null && echo "FIREFOX=YES" || echo "FIREFOX=NO"
dpkg -l | grep -i 'chromium\|chrome\|firefox' 2>/dev/null | head -5 || true
