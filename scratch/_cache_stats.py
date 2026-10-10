"""Статистика кэша внешнего разбора pdf/doc."""
import json
import os

CACHE = os.getenv("DIRECT_PARSE_CACHE", "/var/cache/crm_direct_parse")

total = with_tables = with_lines = errors = empty = 0
by_error = {}
for name in os.listdir(CACHE):
    if not name.endswith(".json"):
        continue
    total += 1
    try:
        with open(os.path.join(CACHE, name), encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        by_error["cache_read:" + type(exc).__name__] = by_error.get("cache_read:" + type(exc).__name__, 0) + 1
        continue
    if doc.get("error"):
        errors += 1
        key = str(doc["error"])[:40]
        by_error[key] = by_error.get(key, 0) + 1
    if doc.get("tables"):
        with_tables += 1
    if doc.get("lines"):
        with_lines += 1
    if not doc.get("tables") and not doc.get("lines") and not doc.get("error"):
        empty += 1

print("cache=%s" % CACHE)
print("files=%d with_tables=%d with_lines=%d empty=%d errors=%d" % (
    total, with_tables, with_lines, empty, errors))
for key, count in sorted(by_error.items(), key=lambda x: -x[1])[:12]:
    print("   %-40s %s" % (key, count))
