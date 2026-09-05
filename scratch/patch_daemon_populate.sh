#!/bin/bash
# Patch daemon.py to skip legacy populate_coordinator when PROCESSING_BACKEND=S13_V2
python3 << 'PYEOF'
import re

filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py'
with open(filepath, 'r') as f:
    content = f.read()

# Find and wrap populate_coordinator call with backend check
old = '''        try:
            self.populate_coordinator.populate_if_needed(pending_count)
        except Exception as exc:
            self.logger.error(f"Ошибка при пополнении очереди: {exc}", exc_info=True)'''

new = '''        try:
            if os.getenv("PROCESSING_BACKEND") != "S13_V2":
                # S13_V2 uses populate_all_eligible() externally — skip legacy populate
                self.populate_coordinator.populate_if_needed(pending_count)
        except Exception as exc:
            self.logger.error(f"Ошибка при пополнении очереди: {exc}", exc_info=True)'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print('PATCHED: skip legacy populate when PROCESSING_BACKEND=S13_V2')
else:
    print('PATTERN NOT FOUND, searching...')
    idx = content.find('populate_coordinator.populate_if_needed')
    if idx != -1:
        print(f'Found at char {idx}:')
        print(repr(content[max(0, idx-100):idx+200]))
PYEOF

python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py && echo "SYNTAX_OK"
