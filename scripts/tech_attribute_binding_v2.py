"""TECH_ATTRIBUTE_BINDING_V2_PRECISION.

Отличия от V1:
  * значение берётся ТОЛЬКО по тип-специфичному паттерну рядом с attribute_name
    (никакого «ближайшего числа»); м2/м²/м3/м³ не распадаются на «м»+цифру;
  * у каждого типа свой допустимый value pattern:
      DIMENSIONAL (THICKNESS/LENGTH/WIDTH/HEIGHT/DIAMETER) -> число + единица длины
      STRENGTH_CLASS -> B7.5/B15/В20
      FIRE_HAZARD_CLASS -> КМ0..КМ5 (+ сохранение бандла Г1/В2/Д2/Т2/РП)
      APPLICATION_CLASS -> 21..43 или 34/43
  * материал хранится двумя представлениями (material_raw / material_normalized)
    как noun phrase, без обрезки до первого знакомого корня;
  * приоритет привязки: same row > inherited row > context row > ambiguous.

Ограничения: HTTP=0, CRM/queue/writers не трогаются (CRM читается только на чтение).
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

DIMENSION_UNITS = r"(мм|см|мкм|м)"
_DIM = r"(\d+(?:[.,]\d+)?)\s*" + DIMENSION_UNITS

#: Тип -> (имя-паттерн, value-паттерн). Окно ограничено: ищем рядом с названием.
TYPE_SPECS = {
    "THICKNESS": (re.compile(r"толщин\w*", re.I), re.compile(r"толщин\w*[^|]{0,40}?" + _DIM, re.I)),
    "LENGTH": (re.compile(r"длин\w*", re.I), re.compile(r"длин\w*[^|]{0,40}?" + _DIM, re.I)),
    "WIDTH": (re.compile(r"ширин\w*", re.I), re.compile(r"ширин\w*[^|]{0,40}?" + _DIM, re.I)),
    "HEIGHT": (re.compile(r"высот\w*", re.I), re.compile(r"высот\w*[^|]{0,40}?" + _DIM, re.I)),
    "DIAMETER": (re.compile(r"диаметр\w*", re.I), re.compile(r"диаметр\w*[^|]{0,40}?" + _DIM, re.I)),
    "STRENGTH_CLASS": (
        re.compile(r"(?:класс\w*\s*(?:прочност\w*|бетон\w*)|бетон\w*[^|]{0,40}?)\s*[вb]\s?\d{1,3}(?:[.,]\d+)?", re.I),
        re.compile(r"(?:класс\w*\s*(?:прочност\w*|бетон\w*)|бетон\w*[^|]{0,40}?)\s*([вb]\s?\d{1,3}(?:[.,]\d+)?)", re.I),
    ),
    "FIRE_HAZARD_CLASS": (
        re.compile(r"класс\w*\s*пожарн\w*\s*опасност\w*", re.I),
        re.compile(r"класс\w*\s*пожарн\w*\s*опасност\w*[^|]{0,20}?(км\s?[0-5])(\s*\([^)]*\))?", re.I),
    ),
    "APPLICATION_CLASS": (
        re.compile(r"класс\w*\s*(?:применени\w*|износостойкост\w*)", re.I),
        re.compile(r"класс\w*\s*(?:применени\w*|износостойкост\w*)[^0-9]{0,20}?"
                   r"((?:2[13]|3[1234]|4[123])(?:\s*/\s*(?:2[13]|3[1234]|4[123]))?)", re.I),
    ),
}

MATERIAL_ROOTS = tuple("""
линолеум гкл гипсокартон бетон раствор смес асфальтобетон щебен песок цемент арматур
сталь труб профил плитк керамогранит кабел провод лампа светильник пленк мастик праймер
грунтов шпаклев кирпич блок утеплител минват пенопласт фанер брус доск панел мембран
рубероид герметик краск эмал решетк сетк крепеж болт гайк саморез анкер дюбел шуруп
подшипник клапан задвижк насос счетчик щит шкаф трансформатор радиатор котел
""".split())

_WORD_RE = re.compile(r"[а-яёa-z0-9\-]{2,}", re.I)
_PRICE_QTY_RE = re.compile(r"(цена|стоимость|количество|итого|руб|₽)", re.I)


def norm_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def protect_units(text: str) -> str:
    """м2/м²/м3/м³ — целые токены, а не «м» + цифра."""
    return (text.replace("м²", "м2").replace("м³", "м3")
                .replace("М²", "м2").replace("М³", "м3"))


def unit_digit_guard(text: str, number: str) -> bool:
    """True, если число — это цифра из единицы измерения (м2/м3), а не значение."""
    idx = text.find(number)
    while idx != -1:
        if idx > 0 and text[idx - 1] in ("м", "М") and len(number) == 1:
            return True
        idx = text.find(number, idx + 1)
    return False


def material_phrase(segment: str):
    """Noun phrase материала: не режем до первого корня, берём с окружением."""
    words = segment.split()
    for idx, word in enumerate(words):
        low = word.lower().strip(".,;:()[]«»\"'")
        if any(low.startswith(root) for root in MATERIAL_ROOTS):
            # слева берём только прилагательное (не номер строки/код/служебное слово),
            # справа — до двух слов noun phrase
            prev = words[idx - 1] if idx > 0 else ""
            if not re.search(r"\d", prev) and re.search(r"(ая|ые|ый|ой|ого|ых|ий)$", prev.lower()):
                head = [prev, word]
            else:
                head = [word]
            phrase = " ".join(head + words[idx + 1:idx + 3]).strip(" .,;:()[]«»\"'")
            # не затягиваем в материал слова параметра и служебные обрывки
            phrase = re.split(
                r"\b(?:толщин\w*|класс\w*|диаметр\w*|длин\w*|ширин\w*|высот\w*|масс\w*|объ[её]м\w*"
                r"|площад\w*|цена|стоимость|количество|итого|вес)\b",
                phrase, flags=re.I)[0].strip(" .,;:()[]«»\"'")
            return phrase or None
    return None


def normalize_material(phrase: str | None) -> str | None:
    if not phrase:
        return None
    low = norm_text(phrase).lower().replace("ё", "е")
    low = re.sub(r"[«»\"'.,;:()]", "", low)
    if "керамогранит" in low and "плит" in low:
        return "керамогранитная плитка"
    if "гипсокартон" in low and "гклв" in low:
        return "гипсокартон влагостойкий"
    if "гипсокартон" in low and "гкло" in low:
        return "гипсокартон огнестойкий"
    if "гипсокартон" in low:
        return "гипсокартон"
    if "линолеум" in low:
        return "линолеум пвх" if "пвх" in low else "линолеум"
    low = re.sub(r"\b(?:тяжелого|тяжелый|тяжёлый)\s+бетон\b", "бетон тяжелый", low)
    low = re.sub(r"\bбетон\s+(?:тяжелого|тяжелый|тяжёлый)\b", "бетон тяжелый", low)
    return re.sub(r"\s+", " ", low).strip()


def extract_value_v2(attribute_type: str, text: str):
    """(value_raw, value_normalized, unit) строго по типу и в окне параметра."""
    _, value_re = TYPE_SPECS[attribute_type]
    match = value_re.search(text)
    if not match:
        return None, None, None
    raw = match.group(0).strip()
    if _PRICE_QTY_RE.search(raw):
        return None, None, None
    if attribute_type in ("THICKNESS", "LENGTH", "WIDTH", "HEIGHT", "DIAMETER"):
        number, unit = match.group(1), match.group(2)
        if unit_digit_guard(text, number):
            return None, None, None
        # число не должно быть цифрой из единицы (м2/м3) — страховка на будущее
        pos = match.start(1)
        if pos > 0 and text[pos - 1] in ("м", "М"):
            return None, None, None
        value = float(number.replace(",", "."))
        u = unit.lower()
        if u.startswith("см"):
            value, unit_norm = round(value * 10, 4), "MM"
        elif u.startswith("мкм"):
            value, unit_norm = round(value / 1000, 6), "MM"
        elif u == "м":
            value, unit_norm = round(value * 1000, 4), "MM"
        else:
            unit_norm = "MM"
        pretty = ("%g" % value)
        return raw, pretty, unit_norm
    if attribute_type == "STRENGTH_CLASS":
        value = match.group(1).upper().replace("В", "B").replace(" ", "")
        return raw, value, None
    if attribute_type == "FIRE_HAZARD_CLASS":
        km = match.group(1).upper().replace(" ", "")
        bundle = (match.group(0) or "").strip()
        return bundle, "KM" + km[-1], None
    if attribute_type == "APPLICATION_CLASS":
        return raw, match.group(1).replace(" ", ""), None
    return None, None, None


def detect_attributes(text: str):
    found = []
    for attribute_type, (name_re, _) in TYPE_SPECS.items():
        m = name_re.search(text)
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
    ap.add_argument("--canary", type=int, default=100)
    ap.add_argument("--out", default="/tmp/tech_binding_v2.json")
    args = ap.parse_args()

    conn = connect_di()
    conn.set_session(readonly=True, autocommit=False)
    cur = conn.cursor(name="tab_v2")
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
    err = Counter()
    canary = defaultdict(list)
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
        text = protect_units(" | ".join(pieces))
        if not text:
            continue
        # 100 строк с несколькими числами/единицами — отдельная страта canary
        if len(re.findall(r"\d", text)) >= 8 and len(re.findall(DIMENSION_UNITS, text)) >= 2:
            if len(canary["MULTI_NUMBER_ROWS"]) < args.canary:
                canary["MULTI_NUMBER_ROWS"].append({"row": text[:200], "detail_id": detail_id})
        attrs = detect_attributes(text)
        if not attrs:
            continue
        ctx_before_text = " | ".join(str(x) for x in (ctx_b or [])[-3:])
        ctx_after_text = " | ".join(str(x) for x in (ctx_a or [])[:3])
        for attribute_type, attribute_name in attrs:
            value_raw, value_norm, unit = extract_value_v2(attribute_type, text)
            same_row_material = material_phrase(text)
            inherited = material_phrase(ctx_before_text)
            ctx_next = material_phrase(ctx_after_text)
            if same_row_material:
                material_raw, relation, source = same_row_material, "CONFIRMED", "same_row"
            elif inherited:
                material_raw, relation, source = inherited, "CANDIDATE", "inherited_row"
            elif ctx_next:
                material_raw, relation, source = ctx_next, "CANDIDATE", "context_next"
            else:
                material_raw, relation, source = None, "CANDIDATE", "ambiguous"
            if value_norm is None and material_raw is None:
                continue
            type_counts[attribute_type] += 1
            if value_raw:
                with_value += 1
            if unit:
                with_unit += 1
            if material_raw:
                with_material += 1
            else:
                ambiguous += 1
            # --- контроль ошибок ---
            if value_norm and value_raw and unit_digit_guard(text, value_norm):
                err["UNIT_DIGIT_AS_VALUE"] += 1
            if value_raw:
                vpos = text.find(value_raw)
                if vpos >= 0:
                    tail = text[vpos + len(value_raw):vpos + len(value_raw) + 6]
                    head25 = text[max(0, vpos - 12):vpos]
                    if re.search(r"(руб|₽)", tail, re.I) or re.search(
                            r"(цена|стоимость|количество|итого)\s*$", head25, re.I):
                        err["PRICE_OR_QTY_AS_ATTRIBUTE_VALUE"] += 1
            row_index = re.match(r"\s*(\d{1,4})[.)\s]", text)
            if value_raw and row_index and value_norm and value_norm == row_index.group(1):
                err["ROW_NUMBER_AS_VALUE"] += 1
            if material_raw and relation == "CONFIRMED" and material_raw.lower() not in text.lower():
                err["CROSS_MATERIAL_BINDINGS"] += 1
            if material_raw and re.search(r"(ая|ые|ый|ой|ого|ых)$", material_raw) and len(material_raw.split()) == 1:
                err["MATERIAL_TRUNCATED_WRONGLY"] += 1
            rec = {
                "attribute_type": attribute_type,
                "attribute_name": attribute_name,
                "value_raw": value_raw,
                "value_normalized": value_norm,
                "unit": unit,
                "material_raw": material_raw,
                "material_normalized": normalize_material(material_raw),
                "relation_status": relation,
                "relation_source": source,
                "source_row": text[:220],
                "detail_id": detail_id,
                "procurement_id": pid,
            }
            if len(canary[attribute_type]) < args.canary:
                canary[attribute_type].append(rec)
    conn.close()

    print("TECH_ROWS_INPUT", rows_input)
    print("ATTRIBUTE_TOTAL_AFTER", sum(type_counts.values()))
    print("ATTRIBUTE_WITH_VALUE_AFTER", with_value)
    print("ATTRIBUTE_WITH_UNIT_AFTER", with_unit)
    print("ATTRIBUTE_WITH_MATERIAL_AFTER", with_material)
    print("AMBIGUOUS_AFTER", ambiguous)
    print("BY_TYPE", json.dumps(dict(type_counts), ensure_ascii=False))
    for key in ("THICKNESS", "DIAMETER", "STRENGTH_CLASS", "FIRE_HAZARD_CLASS", "APPLICATION_CLASS"):
        print("%s_NORMALIZED=" % key, type_counts.get(key, 0))
    for key in ("VALUE_FALSE_BINDINGS", "UNIT_DIGIT_AS_VALUE", "ROW_NUMBER_AS_VALUE",
                "PRICE_OR_QTY_AS_ATTRIBUTE_VALUE", "MATERIAL_TRUNCATED_WRONGLY",
                "CROSS_MATERIAL_BINDINGS"):
        print("%s=%d" % (key, err.get(key, 0)))
    print("HTTP_REQUESTS=0  CRM_WRITES=0  QUEUE_WRITES=0")
    print()
    for key in ("THICKNESS", "DIAMETER", "STRENGTH_CLASS", "FIRE_HAZARD_CLASS", "APPLICATION_CLASS"):
        print("CANARY_%s (%d)" % (key, len(canary[key])))
        for r in canary[key][:5]:
            print("   material_raw=%-24s norm=%-22s value=%-10s unit=%-5s rel=%s" %
                  (str(r["material_raw"])[:24], str(r["material_normalized"])[:22],
                   str(r["value_normalized"])[:10], str(r["unit"])[:5], r["relation_status"]))
            print("      value_raw:", str(r["value_raw"])[:90])
            print("      row:", str(r["source_row"])[:100])
    print("CANARY_MULTI_NUMBER_ROWS (%d)" % len(canary["MULTI_NUMBER_ROWS"]))

    report = {
        "tech_rows_input": rows_input,
        "attribute_total_after": sum(type_counts.values()),
        "attribute_with_value_after": with_value,
        "attribute_with_unit_after": with_unit,
        "attribute_with_material_after": with_material,
        "ambiguous_after": ambiguous,
        "by_type": dict(type_counts),
        "errors": dict(err),
        "canary": {k: v for k, v in canary.items()},
        "http_requests": 0, "crm_writes": 0, "queue_writes": 0,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("REPORT_WRITTEN", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
