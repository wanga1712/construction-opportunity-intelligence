"""Исправление блока tab_supply: тело должно лежать внутри with (одноразово)."""
from pathlib import Path

path = Path("src/ui/procurement_card_page.py")
text = path.read_bytes().decode("utf-8")
eol = "\r\n" if "\r\n" in text else "\n"
lines = text.replace("\r\n", "\n").split("\n")

guard = next(i for i, l in enumerate(lines) if l.strip() == "if tab_supply is not None:")
with_line = guard + 1
assert lines[with_line].strip() == "with tab_supply:", lines[with_line]
end = with_line + 1
while end < len(lines) and (not lines[end].strip() or lines[end].startswith(" " * 8)):
    end += 1
for i in range(with_line + 1, end):
    if lines[i].strip():
        lines[i] = "    " + lines[i]
path.write_bytes(eol.join(lines).encode("utf-8"))
print("guard=%d with=%d body=%d..%d" % (guard + 1, with_line + 1, with_line + 2, end))
print("next non-indented line:", repr(lines[end][:60]))
