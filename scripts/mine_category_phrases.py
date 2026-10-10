"""Mine repeated normalized phrases from document raw cells -> category candidates.

Usage on S13:
  PYTHONPATH=/opt/CRM_Streamlit:/opt/tender_documents_research \
  MINER_LIMIT=200000 /opt/CRM_Streamlit/.venv313/bin/python scripts/mine_category_phrases.py

Read-only over document_match_details; writes only to category_phrase_candidates.
Rule (agreed): candidate = phrase in >=5 distinct procurements AND >=8 occurrences,
inside one OKPD cluster, and not already covered by CATEGORY_TERMS.

NOTE: requires a unit of measure in the cell and drops legal/administrative
boilerplate; the remaining buckets are "product/category", "technical parameter"
(длина/ширина/глубина/габарит…) and junk.
"""
import os
import re
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=True)
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/tender_documents_research")

import psycopg2  # noqa: E402

from src.services.commercial_routing_v3.text_normalization import canonical_tokens  # noqa: E402
from document_processor.smeta_forma_4b import CATEGORY_TERMS  # noqa: E402

BATCH = 20000
LIMIT = int(os.environ.get("MINER_LIMIT", "200000"))
MIN_PROC = 5
MIN_OCC = 8

KNOWN = tuple(n for needles in CATEGORY_TERMS.values() for n in needles)
_SPLIT = re.compile(r"[|;,\n]+")

# Legal / administrative boilerplate stems (44-ФЗ, contract, application text).
BOILERPLATE = frozenset("""
российск федерац участник участник закупк закупк закупочн заказчик поставщик исполнител подрядчик
документ документац информац извещени протокол комисси комиссион заявк заявлен лот аукцион конкурс
контракт договор соглашени приложени раздел таблиц лист граф строка пункт подпункт абзац примечани
законодательств закон нормативн правов регулирующ требован соответств соответствии исключением
числе том весь иной проч другое следующий указанн вышеуказанн настоящ котор должн может не
средств денежн бюджет субсиди финансировани оплат цена стоимость сумма рубл копейк ндс налог
банковск гаранти обеспечени задаток аванс платеж расчет счет казначейств
срок дата период начал окон чани момент день месяц квартал год
качеств техническ задани гост снип строительн норма правил ту регламент лицензи сертификат
приемк исполнени обязательств ответственн неустойк штраф пеня претензи гарантийн
электронн площадк торгов оператор функционал личный кабинет регистрац аккредитац подпис
юридическ физическ лицо лицо индивидуальн предпринимател наименовани адрес инн кпп огрн
получател отправител грузополучател реквизит банк бенефициар
объект территор район област город муниципальн государственн социальн
выполнени оказани поставк работ услуг мероприяти реализац
необходим возможно отсутств наличи определ установлен применен использ
предоставл направл осуществл являет имеет
""".split())


_UNIT_RE = re.compile(
    r"(^|\s)(шт|м2|м3|м|кг|г|т|л|мл|компл|упак|пач|рул|пог\.?м|км|руб)\.?($|\s)",
    re.IGNORECASE,
)


def _is_boilerplate(tokens):
    for tok in tokens:
        for root in BOILERPLATE:
            if len(root) >= 5 and tok.startswith(root):
                return True
    return False


def _has_unit(fragment: str) -> bool:
    return bool(_UNIT_RE.search(fragment))


# Technical/geometric parameters and price/quantity words: these describe the
# OBJECT, not a sellable product ("длина моста", "глубина заложения", "цена").
PARAM_ROOTS = tuple("""
длин ширин высот глубин габарит диаметр масс объем площад расстояни толщин мощност
производительн давлени температу скорост уклон отметк координат цена стоимост количеств
единиц срок номер шифр пункт верси индекс коэффициен норматив процент этап участок
километр гектар литр тонн килограмм штук градус атмосфер квт мегапаскал напряжени частот
расход запас ресурс класс тип вид марк сери модел артикул размер формат цвет оттенок
""".split())

# Product/material head nouns: a phrase is only a category candidate if it names
# something sellable.
MATERIAL_ROOTS = tuple("""
светильник лампа кабел провод труб лоток плитк керамогранит линолеум ламинат паркет
плинтус бордюр камень арматур профил лист панел мембран мастик рубероид праймер
герметик краск эмал грунтов шпаклев смес бетон раствор кирпич блок утеплител минват
пенопласт гипсокартон фанера брус доск рейк металлочерепиц профнастил сайдинг кран
насос вентил задвижк клапан счетчик щит шкаф трансформатор генератор кондиционер
радиатор котел коллектор фильтр резервуар емкост опор ферм балк ригел колонн сва
сетк решетк люк дождеприемник трап унитаз раковин смесител ванн двер окн ворот замок
петл стекл зеркал крепеж болт гайк саморез анкер дюбел шуруп хомут скоб кронштейн
гофр изоляц лента пленк полос швеллер уголок двутавр рулон ткань канат трос цеп
подшипник сальник прокладк манжет
""".split())


def _has_root(tokens, roots) -> bool:
    for tok in tokens:
        for root in roots:
            if len(root) >= 4 and tok.startswith(root):
                return True
    return False


def _is_parameter(tokens) -> bool:
    return _has_root(tokens, PARAM_ROOTS)


def _has_material(tokens) -> bool:
    return _has_root(tokens, MATERIAL_ROOTS)


def fragments(row_data):
    if not isinstance(row_data, dict):
        return
    for section in ("values", "headers"):
        part = row_data.get(section)
        if isinstance(part, dict):
            for value in part.values():
                yield str(value)
    for cell in row_data.get("raw_cells") or []:
        if isinstance(cell, dict):
            for key in ("text", "header"):
                if cell.get(key):
                    yield str(cell[key])


counter = defaultdict(int)
quotes = {}
procs = defaultdict(set)

conn = psycopg2.connect(
    host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
    dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
)
conn.set_session(readonly=True, autocommit=False)
cur = conn.cursor(name="miner")
cur.itersize = BATCH
cur.execute(
    """SELECT procurement_id, row_data FROM document_match_details
       WHERE row_data IS NOT NULL AND row_data::text <> '{}'
       ORDER BY id DESC LIMIT %s""",
    (LIMIT,),
)

seen_rows = 0
for pid, row_data in cur:
    seen_rows += 1
    if seen_rows % 50000 == 0:
        print("PROGRESS", seen_rows, "phrases", len(counter), flush=True)
    for fragment in fragments(row_data):
        if not _has_unit(fragment):
            continue
        if len(fragment) > 140:
            continue
        lowered = fragment.lower()
        if any(k in lowered for k in KNOWN):
            continue
        for chunk in _SPLIT.split(fragment):
            tokens = canonical_tokens(chunk)
            if len(tokens) < 2 or len(tokens) > 25:
                continue
            for size in (2,):
                for i in range(len(tokens) - size + 1):
                    window = tokens[i:i + size]
                    if _is_boilerplate(window):
                        continue
                    if _is_parameter(window) or not _has_material(window):
                        continue
                    phrase = " ".join(window)
                    if len(phrase) < 8:
                        continue
                    counter[phrase] += 1
                    if phrase not in quotes:
                        quotes[phrase] = chunk.strip()[:300]
                    if counter[phrase] >= 3:
                        procs[phrase].add(pid)

print("ROWS", seen_rows, "CANDIDATE_PHRASES", len(counter), flush=True)

rows = []
for phrase, occ in counter.items():
    if occ < MIN_OCC:
        continue
    distinct = len(procs.get(phrase, ()))
    if distinct < MIN_PROC:
        continue
    rows.append((phrase, occ, distinct, quotes.get(phrase, "")))
rows.sort(key=lambda r: (-r[2], -r[1]))
print("PASSING", len(rows))
for row in rows[:25]:
    print("CAND", row[2], "procs", row[1], "occ |", row[0].encode("unicode_escape").decode("ascii")[:80])

# Persist candidates (writable connection; the mining one is read-only).
write = psycopg2.connect(
    host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
    dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
)
wc = write.cursor()
saved = 0
for phrase, occ, distinct, quote in rows:
    wc.execute(
        """INSERT INTO category_phrase_candidates
             (phrase_normalized, occurrences, distinct_procurements, bucket,
              status, example_quote)
           VALUES (%s,%s,%s,'CATEGORY_CANDIDATE','NEW',%s)
           ON CONFLICT (phrase_normalized) DO UPDATE
             SET occurrences = GREATEST(category_phrase_candidates.occurrences, EXCLUDED.occurrences),
                 distinct_procurements = GREATEST(category_phrase_candidates.distinct_procurements,
                                                  EXCLUDED.distinct_procurements),
                 last_seen_at = NOW()""",
        (phrase, occ, distinct, quote),
    )
    saved += 1
write.commit()
print("SAVED", saved)
write.close()
conn.close()
