"""Механическая переиндентация блока tab_supply после обёртки в if (одноразово)."""
from pathlib import Path

path = Path("src/ui/procurement_card_page.py")
text = path.read_bytes().decode("utf-8")
eol = "\r\n" if "\r\n" in text else "\n"
lines = text.replace("\r\n", "\n").split("\n")

start = next(i for i, l in enumerate(lines) if l.strip() == "with tab_supply:")
assert lines[start - 1].strip() == "if tab_supply is not None:", lines[start - 1]
body_start = start + 1
end = body_start
while end < len(lines):
    line = lines[end]
    if line.strip() and not line.startswith(" " * 12):
        break
    end += 1
changed = 0
for i in range(body_start, end):
    if lines[i].strip():
        lines[i] = "    " + lines[i]
        changed += 1
path.write_bytes(eol.join(lines).encode("utf-8"))
print("reindented lines %d..%d (%d non-empty)" % (body_start + 1, end, changed))
print("block ends before:", repr(lines[end][:70]))
