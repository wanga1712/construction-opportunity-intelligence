#!/usr/bin/env python3
"""Saturate background CPUs 2-7 only; keep reserved 0-1 free. Duration seconds."""
from __future__ import annotations

import os
import sys
import time
from multiprocessing import Process


def burn() -> None:
    x = 0
    while True:
        x = (x + 1) & 0xFFFFFFFF


def main() -> None:
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    cpus = [2, 3, 4, 5, 6, 7]
    procs: list[Process] = []
    for cpu in cpus:
        p = Process(target=burn, daemon=True)
        p.start()
        os.sched_setaffinity(p.pid, {cpu})
        procs.append(p)
    time.sleep(duration)


if __name__ == "__main__":
    main()
