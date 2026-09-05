import json
import re

transcript_path = r"C:\Users\Lenovo\.gemini\antigravity\brain\da7610a5-dc1b-4aac-9953-086d1220a9e4\.system_generated\logs\transcript.jsonl"

with open(transcript_path, "r", encoding="utf-8") as f:
    for line_num, line in enumerate(f, 1):
        if "bounded batch" in line or "3 CONFIRMED" in line or "3 REJECTED" in line or "38182" in line:
            print(f"Line {line_num}:")
            try:
                obj = json.loads(line)
                content = str(obj.get("content", ""))
                thinking = str(obj.get("thinking", ""))
                text = content + thinking
                for match in re.finditer(r"3818[2-7].{0,100}", text):
                    print("  Match:", match.group(0))
                if "CONFIRMED" in text and "3818" in text:
                    print("  Full line snippet:", text[:500])
            except Exception as e:
                print("  Parse error:", e)
