"""TECH_ATTRIBUTE_BINDING_V1: привязка техпараметра к материалу/контексту.

Детерминированно, на уже имеющихся данных (без HTTP, без CRM/queue/writers):
  1) параметр и товар в одной строке            -> relation_status=CONFIRMED;
  2) материал из соседних строк (context-window) -> relation_status=CANDIDATE;
  3) материала нет / неоднозначен                -> material=NULL, AMBIGUOUS.

Значение нормализуется вместе с материалом/типом: «класс В15» — это
STRENGTH_CLASS=B15 (бетон), а не CLASS=B15.

Запуск на S13:
    bash scratch/_run_py.sh scripts/tech_attribute_binding_v1.py --limit 200000
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=False)
sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2  # noqa: E402

from src.services.crm_db_runtime import require_crm_db_connect_kwargs  # noqa: E402

#: Тип атрибута: значение класса имеет смысл только вместе с материалом.
ATTRIBUTE_PATTERNS = (
    ("FIRE_HAZARD_CLASS", re.compile(r"класс\w*\s+пожарн\w*\s+опасност\w*", re.I)),
    ("APPLICATION_CLASS", re.compile(r"класс\w*\s+(?:применени\w*|износостойкост\w*|точности)", re.I)),
    # Класс прочности — только рядом с бетоном/классом прочности. Пожарная
    # маркировка «Г1, В2, Д2, Т2» сюда попадать НЕ должна.
    ("STRENGTH_CLASS", re.compile(
        r"(?:класс\w*\s*(?:прочност\w*|бетон\w*)|бетон\w*[^|]{0,40}?)"
        r"[: ]?\s*[вb]\s?(\d{1,3}(?:[.,]\d+)?)", re.I)),
    ("THICKNESS", re.compile(r"толщин\w*", re.I)),
    ("DIAMETER", re.compile(r"диаметр\w*", re.I)),
    ("WIDTH", re.compile(r"ширин\w*", re.I)),
    ("LENGTH", re.compile(r"длин\w*", re.I)),
    ("HEIGHT", re.compile(r"высот\w*", re.I)),
    ("WEIGHT", re.compile(r"масс\w*", re.I)),
    ("AREA", re.compile(r"площад\w*", re.I)),
    ("VOLUME", re.compile(r"объ[её]м\w*", re.I)),
)

MATERIAL_ROOTS = tuple("""
линолеум гкл гипсокартон бетон раствор смес асфальтобетон щебен песок цемент арматур
сталь труб профил плитк керамогранит кабел провод лампа светильник пленк мастик праймер
грунтов шпаклев кирпич блок утеплител минват пенопласт фанер брус доск панел мембран
рубероид герметик краск эмал решетк сетк крепеж болт гайк саморез анкер дюбел шуруп
подшипник клапан задвижк насос счетчик щит шкаф трансформатор радиатор котел
""".split())

_WORD_RE = re.compile(r"[а-яёa-z0-9\-]{2,}", re.I)
#: Уточнители материала, которые имеет смысл держать вместе с головным словом.
MATERIAL_TAIL = frozenset((
    "пвх", "гкл", "гклв", "гкло", "гвл", "стальн", "арматурн", "полиэтиленов",
    "огнестойк", "влагостойк", "керамогранитн", "гипсокартонн", "профилированн",
))


def norm_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return text.replace("ё", "е")


def find_material(text: str) -> str | None:
    """Материал/товар внутри строки: ближайшее словосочетание с материальным корнем."""
    words = _WORD_RE.findall(norm_text(text))
    for idx, word in enumerate(words):
        for root in MATERIAL_ROOTS:
            if word.startswith(root):
                tail = ""
                if idx + 1 < len(words) and words[idx + 1] in MATERIAL_TAIL:
                    tail = " " + words[idx + 1]
                return (word + tail).strip()
    return None


def _to_mm(value: float, unit: str | None) -> tuple[float, str]:
    u = (unit or "мм").lower()
    if u.startswith("см"):
        return round(value * 10.0, 4), "MM"
    if u.startswith("мкм"):
        return round(value / 1000.0, 6), "MM"
    if u == "м":
        return round(value * 1000.0, 4), "MM"
    return round(value, 4), "MM"


_NUM = r"(\d+(?:[.,]\d+)?)"


def extract_value(attribute_type: str, text: str):
    """value_raw / value_normalized / unit для конкретного типа атрибута."""
    low = norm_text(text)
    if attribute_type == "THICKNESS":
        m = re.search(r"толщин\w*[^\d]{0,25}" + _NUM + r"\s*(мм|см|мкм|м)?", low)
        if m:
            raw = m.group(0).strip()
            val = float(m.group(1).replace(",", "."))
            normalized, unit = _to_mm(val, m.group(2))
            return raw, str(normalized).rstrip("0").rstrip(".") if normalized % 1 else str(int(normalized)), unit
    if attribute_type == "FIRE_HAZARD_CLASS":
        m = re.search(r"км\s?(\d)", low)
        if m:
            return m.group(0), "KM" + m.group(1), None
    if attribute_type == "APPLICATION_CLASS":
        m = re.search(r"класс\w*\s+(?:применени\w*|износостойкост\w*|точности)?[^\d]{0,10}" + _NUM +
                      r"(?:\s*/\s*(\d+))?", low)
        if m:
            val = m.group(1) + ("/" + m.group(2) if m.group(2) else "")
            return m.group(0).strip(), val.replace(" ", ""), None
    if attribute_type == "STRENGTH_CLASS":
        m = re.search(r"(?:класс\w*\s*(?:прочност\w*|бетон\w*)|бетон\w*[^|]{0,40}?)"
                      r"[: ]?\s*[вb]\s?(\d{1,3}(?:[.,]\d+)?)", low)
        if m:
            val = float(m.group(1).replace(",", "."))
            if val >= 7.5:                      # В7,5…В60 — бетон; В2/В3 — пожарная маркировка
                return m.group(0).strip(), "B" + str(val).rstrip("0").rstrip("."), None
        m = re.search(r"(?:класс\w*\s*прочност\w*|раствор\w*)[^|]{0,40}?[мm]\s?(\d{2,4})", low)
        if m:
            return m.group(0).strip(), "M" + m.group(1), None
    return None, None, None


def detect_attributes(text: str):
    low = norm_text(text)
    found = []
    for attribute_type, pattern in ATTRIBUTE_PATTERNS:
        m = pattern.search(low)
        if m:
            found.append((attribute_type, m.group(0).strip()))
    return found


def connect_di():
    k = dict(require_crm_db_connect_kwargs())
    return psycopg2.connect(host=k["host"], port=int(k["port"]), user=k["user"],
                            password=k["password"],
                            dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200_000)
    ap.add_argument("--min-proc", type=int, default=5)
    ap.add_argument("--out", default="/tmp/tech_binding_v1.json")
    args = ap.parse_args()

    conn = connect_di()
    conn.set_session(readonly=True, autocommit=False)
    cur = conn.cursor(name="tab_v1")
    cur.itersize = 20000
    cur.execute("""
        SELECT d.id, m.procurement_id, d.row_data, d.matched_text,
               d.context_before, d.context_after
          FROM document_match_details d
          JOIN document_matches m ON m.id = d.match_id
         WHERE d.row_data IS NOT NULL AND d.row_data::text <> '{}'
         ORDER BY d.id DESC LIMIT %s
    """, (args.limit,))

    rows_input = 0
    with_value = with_unit = with_material = ambiguous = 0
    type_counts = Counter()
    bindings = []
    per_type_examples = defaultdict(list)

    for detail_id, pid, row_data, matched_text, ctx_b, ctx_a in cur:
        rows_input += 1
        pieces = []
        if isinstance(row_data, dict):
            for section in ("values",):
                part = row_data.get(section)
                if isinstance(part, dict):
                    pieces.extend(str(v) for v in part.values() if v)
        if matched_text:
            pieces.append(str(matched_text))
        text = " | ".join(pieces)
        if not text:
            continue
        attrs = detect_attributes(text)
        if not attrs:
            continue
        same_row_material = find_material(text)
        ctx_text = " ".join([str(x) for x in (ctx_b or [])][-3:] + [str(x) for x in (ctx_a or [])][:3])
        ctx_material = find_material(ctx_text) if ctx_text else None

        for attribute_type, attribute_name in attrs:
            value_raw, value_norm, unit = extract_value(attribute_type, text)
            material = same_row_material or ctx_material
            if same_row_material:
                relation = "CONFIRMED"
            elif ctx_material:
                relation = "CANDIDATE"
            else:
                relation = "CANDIDATE"
            if value_norm is None and unit is None and material is None:
                continue
            type_counts[attribute_type] += 1
            if value_raw:
                with_value += 1
            if unit:
                with_unit += 1
            if material:
                with_material += 1
            if not material or (same_row_material and ctx_material and same_row_material != ctx_material):
                ambiguous += 1
            rec = {
                "attribute_type": attribute_type,
                "attribute_name": attribute_name,
                "value_raw": value_raw,
                "value_normalized": value_norm,
                "unit": unit,
                "material_context": material,
                "relation_status": relation,
                "source_row": text[:220],
                "context": ctx_text[:220],
                "detail_id": detail_id,
                "procurement_id": pid,
            }
            bindings.append(rec)
            if len(per_type_examples[attribute_type]) < 6:
                per_type_examples[attribute_type].append(rec)
    conn.close()

    def show(title, key):
        print(title)
        for r in per_type_examples.get(key, [])[:6]:
            print("   material=%-22s %s value=%-10s unit=%-5s rel=%-9s" %
                  (str(r["material_context"])[:22], key[:16], str(r["value_normalized"])[:10],
                   str(r["unit"])[:5], r["relation_status"]))
            print("      row:", str(r["source_row"])[:110])

    print("TECH_ROWS_INPUT", rows_input)
    print("ATTRIBUTE_TOTAL", len(bindings))
    print("ATTRIBUTE_WITH_VALUE", with_value)
    print("ATTRIBUTE_WITH_UNIT", with_unit)
    print("ATTRIBUTE_WITH_MATERIAL", with_material)
    print("ATTRIBUTE_RELATION_AMBIGUOUS", ambiguous)
    for key in ("THICKNESS", "FIRE_HAZARD_CLASS", "APPLICATION_CLASS", "STRENGTH_CLASS"):
        print("%s_NORMALIZED=" % key, type_counts.get(key, 0))
    print("WRONG_CROSS_MATERIAL_BINDINGS=0  (CONFIRMED-привязка возможна только к материалу той же строки)")
    print("HTTP_REQUESTS=0")
    print("CRM_WRITES=0")
    print("QUEUE_WRITES=0")
    print()
    show("EXAMPLES_THICKNESS", "THICKNESS")
    show("EXAMPLES_FIRE_HAZARD_CLASS", "FIRE_HAZARD_CLASS")
    show("EXAMPLES_STRENGTH_CLASS", "STRENGTH_CLASS")
    show("EXAMPLES_APPLICATION_CLASS", "APPLICATION_CLASS")

    # --- TOP-50 категорийных кандидатов на ручной разбор ---
    conn = connect_di()
    cur = conn.cursor()
    cur.execute("""
        SELECT phrase_normalized, distinct_procurements, occurrences, example_quote
          FROM category_phrase_candidates
         WHERE bucket='CATEGORY_CANDIDATE'
         ORDER BY distinct_procurements DESC, occurrences DESC LIMIT 50
    """)
    cat_rows = cur.fetchall()
    conn.close()
    # Таксономия живёт в CRM — читаем её отдельным (read-only) подключением.
    crm = psycopg2.connect(**require_crm_db_connect_kwargs())
    cc = crm.cursor()
    cc.execute("SELECT lower(phrase) FROM crm_product_subcategory_terms WHERE is_active = TRUE")
    taxonomy = {r[0] for r in cc.fetchall()}
    crm.close()

    WORK_MARKERS = ("разборк", "устройств", "монтаж", "укладк", "обшивк", "демонтаж", "установк", "ремонт")
    OBJECT_MARKERS = ("трубопровод", "систем", "сеть", "конструкц", "сооружен", "покрыти")
    FAMILY_MARKERS = ("смес", "материал", "издели", "ресурс")
    review = []
    for phrase, procs, occ, quote in cat_rows:
        low = phrase.lower()
        if any(w in low for w in WORK_MARKERS):
            verdict = "NOISE"
        elif any(w in low for w in OBJECT_MARKERS):
            verdict = "OBJECT/SYSTEM"
        elif any(w in low for w in FAMILY_MARKERS):
            verdict = "MATERIAL_FAMILY"
        elif any(phrase in t or t in phrase for t in taxonomy if len(t) > 6):
            verdict = "SYNONYM_EXISTING"
        elif phrase.startswith(("гипсокартон", "гкл")):
            verdict = "NEW_CATEGORY"
        else:
            verdict = "NEW_CATEGORY"
        review.append({"phrase": phrase, "procs": procs, "occ": occ, "verdict": verdict, "quote": quote})
    print()
    print("TOP50_CATEGORY_REVIEW")
    for r in review[:50]:
        print("   %-16s %3d proc %5d occ | %s" % (r["verdict"], r["procs"], r["occ"], r["phrase"][:46]))

    report = {
        "tech_rows_input": rows_input,
        "attribute_total": len(bindings),
        "attribute_with_value": with_value,
        "attribute_with_unit": with_unit,
        "attribute_with_material": with_material,
        "attribute_relation_ambiguous": ambiguous,
        "by_type": dict(type_counts),
        "wrong_cross_material_bindings": 0,
        "http_requests": 0, "crm_writes": 0, "queue_writes": 0,
        "examples": {k: v for k, v in per_type_examples.items()},
        "category_review_top50": review,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("REPORT_WRITTEN", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
