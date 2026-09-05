#!/bin/bash
python3 << 'PYEOF'
filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py'
with open(filepath, 'r') as f:
    content = f.read()

# Fix the broken indentation from previous patch
old = '''    try:
        if os.getenv("PROCESSING_BACKEND") != "S13_V2":
        daemon.populate_coordinator.populate_on_startup()
    except Exception as exc:
        daemon.logger.error(f"Ошибка стартового пополнения очереди: {exc}", exc_info=True)'''

new = '''    try:
        if os.getenv("PROCESSING_BACKEND") != "S13_V2":
            daemon.populate_coordinator.populate_on_startup()
    except Exception as exc:
        daemon.logger.error(f"Ошибка стартового пополнения очереди: {exc}", exc_info=True)'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print('FIXED indentation in populate_on_startup')
else:
    print('PATTERN NOT FOUND, checking...')
    idx = content.find('populate_on_startup')
    print(repr(content[max(0,idx-200):idx+200]))
PYEOF

python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py && echo "SYNTAX_OK" || echo "SYNTAX_ERROR"
