with open('/opt/tender_documents_research/errors.log') as f:
    lines = f.readlines()
for idx, line in enumerate(lines):
    if 'too many values to unpack' in line:
        for i in range(max(0, idx-40), idx+1):
            print(f"{i}: {lines[i]}", end="")
        break
