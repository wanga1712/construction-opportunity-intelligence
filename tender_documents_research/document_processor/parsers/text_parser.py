from pathlib import Path


class TextParser:
    def parse(self, path: Path) -> str:
        try:
            data = path.read_bytes()
        except Exception:
            return ""
        for encoding in ("utf-8", "cp1251"):
            try:
                return data.decode(encoding, errors="ignore")
            except Exception:
                continue
        return ""

