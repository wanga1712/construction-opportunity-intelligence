#!/bin/bash
FILE="/opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py"

# Fix QueueManager call - it should pass (backend, db) not just (db)
grep -n 'QueueManager' $FILE

# Create the fix
python3 << 'PYEOF'
filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py'
with open(filepath, 'r') as f:
    content = f.read()

# Fix the broken call
old = 'self.queue_manager = QueueManager(self.db)'
new = 'self.queue_manager = QueueManager(self.backend, self.db)'

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print('FIXED QueueManager call')
else:
    print('Pattern not found, checking content:')
    import re
    matches = [(m.start(), m.group()) for m in re.finditer(r'QueueManager\([^)]+\)', content)]
    for pos, m in matches:
        print(f'  Line ~{content[:pos].count(chr(10))+1}: {m}')
PYEOF

python3 -m py_compile $FILE && echo "SYNTAX_OK" || echo "SYNTAX_ERROR"
