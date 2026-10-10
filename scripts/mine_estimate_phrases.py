"""Mine product-name candidates from Форма 4б estimates (Наименование column).

The match-details corpus is dominated by legal/geometric text, so category
discovery runs on the estimate material names instead: for every material line
(unit + price/cost present) take column C, normalize it, and count how many
distinct procurements use it. Candidate = seen in >= MIN_PROC procurements.
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
from document_processor.smeta_forma_4b import (  # noqa: E402
    CATEGORY_TERMS,
    _sheet_members,
    _shared_strings,
    _sheet_rows,
    _unit_of,
    _num,
)

LIMIT = int(os.environ.get("EST_MINER_FILES", "300"))
MIN_PROC = 5
MATERIAL_ROOTS = tuple("""
светильник лампа кабел провод труб лоток плитк керамогранит линолеум ламинат паркет
плинтус бордюр камень арматур профил лист панел мембран мастик рубероид праймер
герметик краск эмал грунтов шпаклев смес бетон раствор кирпич блок утеплител минват
пенопласт гипсокартон фанера брус доск рейк металлочерепиц профнастил сайдинг кран
насос вентил задвижк клапан счетчик щит шкаф трансформатор генератор кондиционер
радиатор котел коллектор фильтр резервуар емкост опор ферм балк ригел колонн сва
сетк решетк люк дождеприемник трап унитаз раковин смесител ванн двер окн ворот замок
петл стекл крепеж болт гайк саморез анкер дюбел шуруп хомут скоб кронштейн гофр
изоляц лента пленк полос швеллер уголок двутавр рулон ткань канат трос цеп
""".split())
KNOWN = tuple(n for needles in CATEGORY_TERMS.values() for n in needles)


def has_material(tokens):
    return any(len(r) >= 4 and t.startswith(r) for t in tokens for r in MATERIAL_ROOTS)


counter = defaultdict(int)
procs = defaultdict(set)
quotes = {}

conn = psycopg2.connect(
    host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
    dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
)
conn.set_session(readonly=True, autocommit=True)
cur = conn.cursor()
pattern = "%" + "\u0441\u043c\u0435\u0442\u0430" + "%.xlsx"
cur.execute(
    """SELECT procurement_id, local_path FROM document_files
       WHERE file_name ILIKE %s AND download_status='COMPLETED' AND local_deleted_at IS NULL
       ORDER BY procurement_id DESC LIMIT %s""",
    (pattern, LIMIT),
)
files = cur.fetchall()
print("FILES", len(files), flush=True)

import zipfile  # noqa: E402

parsed = 0
for pid, path in files:
    try:
        if not path or not os.path.exists(path):
            continue
        with zipfile.ZipFile(path) as zf:
            strings = _shared_strings(zf)
            members = _sheet_members(zf)
            if not members:
                continue
            for _row, cells in _sheet_rows(zf, members[0][1], strings):
                name = str(cells.get("C") or "").strip()
                if not name or not _unit_of(str(cells.get("D") or "")):
                    continue
                if not (_num(cells.get("F")) and _num(cells.get("I"))):
                    continue
                lowered = name.lower()
                if any(k in lowered for k in KNOWN):
                    continue
                tokens = canonical_tokens(name)
                if len(tokens) < 2 or not has_material(tokens):
                    continue
                phrase = " ".join(tokens[:4])
                counter[phrase] += 1
                procs[phrase].add(pid)
                quotes.setdefault(phrase, name[:300])
        parsed += 1
        if parsed % 50 == 0:
            print("PARSED", parsed, "phrases", len(counter), flush=True)
    except Exception as exc:
        print("ERR", pid, str(exc)[:80], flush=True)

rows = [(p, counter[p], len(procs[p]), quotes[p]) for p in counter if len(procs[p]) >= MIN_PROC]
rows.sort(key=lambda r: (-r[2], -r[1]))
print("PARSED_FILES", parsed, "PHRASES", len(counter), "CANDIDATES", len(rows))
for phrase, occ, distinct, quote in rows[:30]:
    print("CAND", distinct, "procs", occ, "occ |", phrase.encode("unicode_escape").decode("ascii")[:70])

if os.environ.get("EST_MINER_SAVE", "1") == "1" and rows:
    write = psycopg2.connect(
        host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
    )
    wc = write.cursor()
    for phrase, occ, distinct, quote in rows:
        wc.execute(
            """INSERT INTO category_phrase_candidates
                 (phrase_normalized, occurrences, distinct_procurements, bucket,
                  status, example_quote)
               VALUES (%s,%s,%s,'CATEGORY_CANDIDATE','NEW',%s)
               ON CONFLICT (phrase_normalized) DO UPDATE
                 SET occurrences = GREATEST(category_phrase_candidates.occurrences, EXCLUDED.occurrences),
                     distinct_procurements = GREATEST(
                         category_phrase_candidates.distinct_procurements,
                         EXCLUDED.distinct_procurements),
                     last_seen_at = NOW()""",
            (phrase, occ, distinct, quote),
        )
    write.commit()
    wc.execute("SELECT bucket, status, COUNT(*) FROM category_phrase_candidates GROUP BY 1,2")
    print("SAVED", rows and len(rows), "TABLE", wc.fetchall())
    write.close()
