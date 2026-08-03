import subprocess
import tempfile
import re
from pathlib import Path
from utils.logger_config import get_logger


class DocParser:
    """Parser for old .doc (binary Word) files.

    Tries several backends in order:
    1. antiword  - lightweight CLI tool
    2. libreoffice --headless  - converts to txt
    3. Raw binary text extraction (fallback)
    """

    def __init__(self):
        self.logger = get_logger()

    def parse(self, path: Path) -> str:
        self.logger.info(f"DocParser: parsing {path.name}...")

        # 1. Try antiword
        text = self._try_antiword(path)
        if text:
            return text

        # 2. Try libreoffice
        text = self._try_libreoffice(path)
        if text:
            return text

        # 3. Fallback: extract readable text from binary
        text = self._extract_raw_text(path)
        if text:
            self.logger.warning(
                f"DocParser: using raw binary fallback for {path.name}, "
                f"extracted {len(text)} chars"
            )
            return text

        self.logger.error(f"DocParser: failed to extract text from {path.name}")
        return ""

    def _try_antiword(self, path: Path) -> str:
        try:
            result = subprocess.run(
                ["antiword", "-m", "UTF-8", str(path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                self.logger.info(
                    f"DocParser: antiword extracted {len(result.stdout)} chars from {path.name}"
                )
                return result.stdout
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            self.logger.warning(f"DocParser: antiword timed out for {path.name}")
        except Exception as e:
            self.logger.debug(f"DocParser: antiword failed for {path.name}: {e}")
        return ""

    def _try_libreoffice(self, path: Path) -> str:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    [
                        "libreoffice",
                        "--headless",
                        "--convert-to",
                        "txt:Text",
                        "--outdir",
                        tmpdir,
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    txt_path = Path(tmpdir) / (path.stem + ".txt")
                    if txt_path.exists():
                        text = txt_path.read_text(encoding="utf-8", errors="ignore")
                        self.logger.info(
                            f"DocParser: libreoffice extracted {len(text)} chars from {path.name}"
                        )
                        return text
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            self.logger.warning(f"DocParser: libreoffice timed out for {path.name}")
        except Exception as e:
            self.logger.debug(f"DocParser: libreoffice failed for {path.name}: {e}")
        return ""

    def _extract_raw_text(self, path: Path) -> str:
        """Last-resort: read binary and extract printable text runs."""
        try:
            raw = path.read_bytes()
        except Exception:
            return ""

        # Try cp1251 (common for Russian .doc files) and utf-8
        for encoding in ("cp1251", "utf-8"):
            try:
                decoded = raw.decode(encoding, errors="ignore")
                # Keep only lines with 3+ printable chars, filter binary garbage
                lines = []
                for line in decoded.splitlines():
                    # Remove non-printable characters except whitespace
                    cleaned = re.sub(r"[^\w\s.,;:!?()\"'\-/\\@#%&*+=<>\[\]{}|~`^$€₽№]", "", line)
                    cleaned = cleaned.strip()
                    # Skip very short or garbage-looking lines
                    if len(cleaned) >= 3 and not self._is_garbage(cleaned):
                        lines.append(cleaned)
                if lines:
                    text = "\n".join(lines)
                    self.logger.info(
                        f"DocParser: raw extraction ({encoding}) got {len(lines)} lines from {path.name}"
                    )
                    return text
            except Exception:
                continue
        return ""

    @staticmethod
    def _is_garbage(line: str) -> bool:
        """Check if a line looks like binary garbage rather than real text."""
        if not line:
            return True
        # If < 30% of chars are letters/digits, it's probably garbage
        alnum = sum(1 for c in line if c.isalnum())
        if len(line) > 0 and alnum / len(line) < 0.3:
            return True
        return False
