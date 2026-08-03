"""OKPD2 prefixes for the computers / IT procurement contour.

Routing is by OKPD from tender_monitor.collection_codes_okpd — not by AI segment
and not by title keywords. Use 26.20* (computers & peripherals), not all of 26.*
(optics / medical devices live under other 26.x branches).
"""
from __future__ import annotations

# Primary contour: computers and peripheral equipment (OKPD2 26.20)
COMPUTER_OKPD_PREFIXES: tuple[str, ...] = (
    "26.20",
    "26.2",  # parent node sometimes stored as main/sub without trailing 0
)

# Explicit allow-list roots used in UI captions / daemon filters
COMPUTER_OKPD_ROOTS: tuple[str, ...] = (
    "26.20",
)

COMPUTER_CATEGORY_NAMES: tuple[str, ...] = (
    "Компьютеры",
)


def compose_okpd_code(main_code: str | None, sub_code: str | None) -> str:
    main = (main_code or "").strip()
    sub = (sub_code or "").strip()
    if main and sub:
        # DB often stores detail in sub_code only (e.g. main=26, sub=26.20.11.110)
        if sub.startswith(main + ".") or sub.startswith(main):
            return sub
        return f"{main}.{sub}"
    return sub or main


def is_computer_okpd(code: str | None, *, name: str | None = None) -> bool:
    """True when OKPD belongs to computers/peripherals contour."""
    raw = compose_okpd_code(None, (code or "").strip()) if code else ""
    # Also accept already-composed codes
    candidates = [c for c in {(code or "").strip(), raw} if c]
    for candidate in candidates:
        normalized = candidate.rstrip(".")
        for prefix in COMPUTER_OKPD_PREFIXES:
            if normalized == prefix or normalized.startswith(prefix + "."):
                return True
        # Some rows store only "26.20.11.110" without dots consistency
        compact = normalized.replace(".", "")
        if compact.startswith("2620"):
            return True
    # Fallback: name hints only when code missing (rare)
    if not candidates and name:
        low = name.lower()
        return any(
            token in low
            for token in ("компьютер", "ноутбук", "моноблок", "сервер", "системн")
        )
    return False
