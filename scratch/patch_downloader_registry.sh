#!/bin/bash
python3 << 'PYEOF'
filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/downloader.py'
with open(filepath, 'r') as f:
    content = f.read()

# Add registry property after state_repo assignment
old = '        self.state_repo = state_repo'
new = '''        self.state_repo = state_repo
        # Alias for backward compatibility with task_pipeline.py which uses .registry
        self.registry = state_repo'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print('PATCHED Downloader: registry = state_repo alias added')
else:
    print('PATTERN NOT FOUND')
    idx = content.find('state_repo')
    print(f'state_repo first occurrence at char {idx}')
    print(repr(content[max(0,idx-50):idx+100]))
PYEOF

python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/downloader.py && echo "SYNTAX_OK"
