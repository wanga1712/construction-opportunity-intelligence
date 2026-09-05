#!/bin/bash
python3 << 'PYEOF'
filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py'
with open(filepath, 'r') as f:
    content = f.read()

# Also patch populate_on_startup
old = '    daemon.populate_coordinator.populate_on_startup()'
new = '''    if os.getenv("PROCESSING_BACKEND") != "S13_V2":
        daemon.populate_coordinator.populate_on_startup()'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print('PATCHED: populate_on_startup guarded for S13_V2')
else:
    print('PATTERN NOT FOUND for populate_on_startup')
    # Print context
    idx = content.find('populate_on_startup')
    if idx != -1:
        print(repr(content[max(0, idx-50):idx+100]))
PYEOF

python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py && echo "SYNTAX_OK"
