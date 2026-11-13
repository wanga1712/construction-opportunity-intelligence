#!/usr/bin/env python3
"""Make the kiosk PROCESSING count parseable by its pipe-based psql reader."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    text = Path(args.source).read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    old_count = "            SELECT count(*)\n              FROM document_processing_queue"
    new_count = "            SELECT 'PROCESSING',count(*)\n              FROM document_processing_queue"
    old_add = ")+(i(qp[0][0]) or 0)"
    new_add = ")+(i(qp[0][1]) or 0)"
    if text.count(old_count) != 1 or text.count(old_add) != 1:
        raise RuntimeError("expected scalar-count anchors not found")
    text = text.replace(old_count, new_count, 1).replace(old_add, new_add, 1)
    Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    print(f"patched={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
