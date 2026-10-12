#!/usr/bin/env python3
"""TIER0 journal breakdown (read-only): HTTP outcomes and failure reasons."""

from __future__ import annotations

import re
import subprocess
import sys


def main() -> int:
    since = sys.argv[1] if len(sys.argv) > 1 else "today"
    out = subprocess.run(
        ["sudo", "journalctl", "-u", "tender-docs-daemon-open.service",
         "--since", since, "--no-pager"],
        capture_output=True, text=True, errors="replace",
    ).stdout

    def c(pat: str) -> int:
        return len(re.findall(pat, out))

    rows = {
        "HTTP_REQUESTS": c(r"Скачивание файла:"),
        "HTTP_200_OK": c(r"Прямое скачивание успешно"),
        "HTTP_404_410": c(r"\b(?:404|410)\b"),
        "HTTP_429": c(r"429 Too Many|rate.?limit|HTTP 429"),
        "CORRUPT_DOCUMENT": c(r"Файл поврежден"),
        "CORRUPT_EOF_MARKER": c(r"EOF marker not found"),
        "CORRUPT_PACKAGE": c(r"Package not found"),
        "INVALID_FILE": c(r"Не удалось получить валидный файл"),
        "UNSUPPORTED_FORMAT": c(r"Unsupported format"),
        "TRANSIENT_ERRORS": c(r"Transient download errors"),
        "RATE_LIMIT_BLOCK": c(r"Global rate-limit block"),
        "NO_RESEARCHABLE_LINKS": c(r"NO_RESEARCHABLE_DOCUMENT_LINKS"),
        "SOFT_FALLBACK_BYPASS": c(r"SOFT_FALLBACK explicit bypass"),
        "TASKS_COMPLETED": c(r"\[S13_V2\]\[\d+\] COMPLETED"),
        "TASKS_FAILED": c(r"\[S13_V2\]\[\d+\] FAILED"),
        "QUEUE_V2_TARGETED": c(r"QUEUE_V2 targeted links"),
        "PARSE_TIME_HOOK_LINES": c(r"parse-time extraction"),
    }
    for k, v in rows.items():
        print(f"{k}={v}")
    embedded = [int(x) for x in re.findall(r"parse-time extraction: facts=\d+ metadata=\d+ embedded=(\d+)", out)]
    print(f"PARSE_TIME_EMBEDDED_SUM={sum(embedded)}")
    # how many targeted tasks resolved exactly the planned count
    planned = re.findall(r"plan_selected=(\d+) resolvable=(\d+)", out)
    mismatch = sum(1 for a, b in planned if a != b)
    print(f"TARGETED_PLANNED_MISMATCH={mismatch}")
    print(f"TARGETED_LINES={len(planned)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
