"""Что осталось без сметы после включения pdf/doc/xls."""
import json
from collections import Counter

rows = [json.loads(l) for l in open("/tmp/direct_batch.jsonl", encoding="utf-8") if l.strip()]
no_spec = [r for r in rows if not r.get("spec")]
print("total=%d no_spec=%d" % (len(rows), len(no_spec)))

ext_counter = Counter()
sig_counter = Counter()
for row in no_spec:
    keys = tuple(sorted((row.get("exts") or {}).keys()))
    ext_counter[",".join(keys)] += 1
    if (row.get("files") or 0) == 0:
        sig_counter["no_files"] += 1
    elif not (row.get("sections") or row.get("tech")):
        sig_counter["nothing_at_all"] += 1
    else:
        sig_counter["has_other_data"] += 1

print("--- форматы у закупок без сметы (топ-10) ---")
for combo, count in ext_counter.most_common(10):
    print("%4d  %s" % (count, combo))
print("--- состояние ---")
for key, count in sig_counter.most_common():
    print("%4d  %s" % (count, key))
only_scan = [r["pid"] for r in no_spec
             if not (r.get("sections") or r.get("tech")) and (r.get("files") or 0) > 0]
print("полностью пустые (вероятно сканы/без текстового слоя): %d" % len(only_scan))
print("примеры:", only_scan[:12])
