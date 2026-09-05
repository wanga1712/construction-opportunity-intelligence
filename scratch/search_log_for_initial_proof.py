import glob
import re

log_files = glob.glob(r"C:\Users\Lenovo\.gemini\antigravity\brain\da7610a5-dc1b-4aac-9953-086d1220a9e4\.system_generated\tasks\*.log")

for f in log_files:
    try:
        with open(f, "r", encoding="utf-8") as file:
            text = file.read()
            if "38182" in text or "38183" in text:
                print(f"=== {f} ===")
                for line in text.splitlines():
                    if any(str(i) in line for i in range(38182, 38188)):
                        print(" ", line[:200])
    except Exception:
        pass
