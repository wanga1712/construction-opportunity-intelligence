"""MINER_V2: повторы фраз из разобранных документов -> кандидаты.

Два независимых бакета:
  CATEGORY_CANDIDATE            — продаваемый товар/материал (для новой категории);
  TECHNICAL_ATTRIBUTE_CANDIDATE — технический параметр (толщина, класс…), для
                                  нормализации значений; unit НЕ обязателен.

Правило кандидата (согласовано): >=5 разных закупок И >=8 вхождений,
OKPD-кластер считается честно (по коду ОКПД закупки, 4 цифры).

Ограничения WIP: HTTP=0, CRM/queue/writers не трогаются. Чтение — из DI
(`document_match_details`) и CRM только на чтение (ОКПД закупки). Запись —
только в собственную таблицу кандидатов в DI.

Запуск на S13:
    bash scratch/_run_py.sh scripts/mine_category_phrases_v2.py            # dry-run
    bash scratch/_run_py.sh scripts/mine_category_phrases_v2.py --persist
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

from src.services.commercial_routing_v3.text_normalization import canonical_tokens  # noqa: E402
from src.services.crm_db_runtime import require_crm_db_connect_kwargs  # noqa: E402

MIN_PROC = 5
MIN_OCC = 8
DEFAULT_LIMIT = 400_000

_SPLIT = re.compile(r"[|;,\n]+")
_NUM_RE = re.compile(r"^\d+(?:[.,/]\d+)*$")
_UNIT_RE = re.compile(
    r"(?:^|\s)(шт|м2|м3|м|мм|см|кг|г|т|л|мл|компл|упак|пач|рул|пог\.?м|км|вт|квт|гц|мгц|ггц"
    r"|в|а|дб|%|руб)\.?(?:$|\s)",
    re.IGNORECASE,
)

BOILERPLATE = frozenset("""
российск федерац участник участник закупк закупк закупочн заказчик поставщик исполнител подрядчик
документ документац информац извещени протокол комисси комиссион заявк заявлен лот аукцион конкурс
контракт договор соглашени приложени раздел таблиц лист граф строка пункт подпункт абзац примечани
законодательств закон нормативн правов регулирующ требован соответств соответствии исключением
числе том весь иной проч другое следующий указанн вышеуказанн настоящ котор должн может не
средств денежн бюджет субсиди финансировани оплат цена стоимость сумма рубл копейк ндс налог
банковск гаранти обеспечени задаток аванс платеж расчет счет казначейств
срок дата период начал окон чани момент день месяц квартал год
качеств задани гост снип строительн норма правил ту регламент лицензи сертификат
приемк исполнени обязательств ответственн неустойк штраф пеня претензи гарантийн
электронн площадк торгов оператор функционал личный кабинет регистрац аккредитац подпис
юридическ физическ лицо индивидуальн предпринимател наименовани адрес инн кпп огрн
получател отправител грузополучател реквизит банк бенефициар
объект территор район област город муниципальн государственн социальн
выполнени оказани работ услуг мероприяти реализац
необходим возможно отсутств наличи определ установлен применен использ
предоставл направл осуществл являет имеет
""".split())

#: Технические параметры: описывают объект/товар, но не являются товаром.
#: Используются ТОЛЬКО для отбора в TECHNICAL_ATTRIBUTE_CANDIDATE — из
#: extraction они НЕ удаляются.
#: Только физико-технические характеристики. Цена/количество/единицы/номер/этап —
#: это не технические атрибуты, а служебные колонки таблиц; они исключены.
PARAM_ROOTS = tuple("""
длин ширин высот глубин габарит диаметр масс объем площад расстояни толщин мощност
производительн давлени температу скорост уклон отметк координат
километр градус атмосфер квт мегапаскал напряжени частот
расход запас ресурс класс тип вид марк сери модел артикул размер формат цвет оттенок
степен огнестойк горюч пожарн примен нагрузк влажност морозостойк плотност
""".split())

#: Дорожная/административная лексика, которая структурно похожа на материал,
#: но товаром не является («полоса отвода», «число полос»).
NON_PRODUCT_PHRASES = (
    "полос отвод", "полос движени", "придорожн полос", "число полос", "транспортн поток",
    "поток полос", "полос движен", "краевая полос", "разделительн полос",
)

#: Служебные колонки таблиц (в том числе короткие корни, которые иначе проходят
#: порог длины стоп-листа).
HEADER_STOP = (
    "единиц измерени", "цена единиц", "цена за единиц", "за единиц", "единиц товар",
    "количество объем", "наименован этап", "цен единиц", "ед изм", "ед измер",
    "общероссийск",
)

#: Административные глаголы: «проводится», «осуществляется» — не материал.
ADMIN_VERBS = ("проводитс", "проводит", "проведен", "выполняютс", "осуществля", "осуществл")

#: Продаваемые товары/материалы.
MATERIAL_ROOTS = tuple("""
светильник лампа кабел труб лоток плитк керамогранит линолеум ламинат паркет
плинтус бордюр камень арматур профил лист панел мембран мастик рубероид праймер
герметик краск эмал грунтов шпаклев смес бетон раствор кирпич блок утеплител минват
пенопласт гипсокартон гкл фанера брус доск рейк металлочерепиц профнастил сайдинг кран
насос вентил задвижк клапан счетчик щит шкаф трансформатор генератор кондиционер
радиатор котел коллектор фильтр резервуар емкост опор ферм балк ригел колонн сва
сетк решетк люк дождеприемник трап унитаз раковин смесител ванн двер окн ворот замок
петл стекл зеркал крепеж болт гайк саморез анкер дюбел шуруп хомут скоб кронштейн
гофр изоляц лента пленк полос швеллер уголок двутавр рулон ткань канат трос цеп
подшипник сальник прокладк манжет обои потолок
""".split())


def _has_root(tokens, roots) -> bool:
    for tok in tokens:
        for root in roots:
            if len(root) >= 4 and tok.startswith(root):
                return True
    return False


def _is_boilerplate(tokens) -> bool:
    for tok in tokens:
        for root in BOILERPLATE:
            if len(root) >= 4 and tok.startswith(root):
                return True
    return False


def _is_non_product(phrase: str) -> bool:
    return any(phrase.startswith(p) or p in phrase for p in NON_PRODUCT_PHRASES)


def _is_header_noise(phrase: str) -> bool:
    return any(phrase.startswith(p) for p in HEADER_STOP)


def _has_unit(fragment: str) -> bool:
    return bool(_UNIT_RE.search(fragment))


def okpd_cluster(okpd_code) -> str:
    """Настоящий OKPD-кластер: первые 4 цифры кода ОКПД2 закупки."""
    raw = re.sub(r"\D", "", str(okpd_code or ""))
    if len(raw) >= 4:
        return raw[:4]
    if raw:
        return raw.ljust(4, "0")
    return "UNKNOWN"


def split_param_value_unit(tokens):
    """param/value/unit для технического кандидата; unit не обязателен."""
    for idx, tok in enumerate(tokens):
        if _NUM_RE.match(tok):
            param = " ".join(tokens[:idx]) or " ".join(tokens[:1])
            unit = tokens[idx + 1] if idx + 1 < len(tokens) and _UNIT_RE.search(" " + tokens[idx + 1] + " ") else None
            return param, tok, unit
    return " ".join(tokens), None, None


def fragments(row_data, matched_text: str = ""):
    if matched_text:
        yield str(matched_text)
    if not isinstance(row_data, dict):
        return
    # Только значения: headers — это названия колонок, а не содержимое закупки.
    for section in ("values",):
        part = row_data.get(section)
        if isinstance(part, dict):
            for value in part.values():
                if value:
                    yield str(value)
    for cell in row_data.get("raw_cells") or []:
        if isinstance(cell, dict):
            for key in ("text", "header"):
                if cell.get(key):
                    yield str(cell[key])


def classify_window(window):
    """Вернуть bucket для n-граммы слов или None."""
    if _is_boilerplate(window):
        return None
    if any(tok.startswith(v) for tok in window for v in ADMIN_VERBS):
        return None
    # Головное слово решает: «гипсокартонные огнестойкие» — товар (голова
    # «гипсокартон»), а не техпараметр, хотя «огнестойкий» есть в PARAM_ROOTS.
    head = window[:1]
    if _has_root(head, MATERIAL_ROOTS):
        return "CATEGORY_CANDIDATE"
    if _has_root(head, PARAM_ROOTS):
        return "TECHNICAL_ATTRIBUTE_CANDIDATE"
    if _has_root(window, PARAM_ROOTS):
        return "TECHNICAL_ATTRIBUTE_CANDIDATE"
    if _has_root(window, MATERIAL_ROOTS):
        return "CATEGORY_CANDIDATE"
    return None


def _connect_di():
    ckw = dict(require_crm_db_connect_kwargs())
    return psycopg2.connect(host=ckw["host"], port=int(ckw["port"]), user=ckw["user"],
                            password=ckw["password"],
                            dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.getenv("MINER_LIMIT", DEFAULT_LIMIT)))
    ap.add_argument("--min-proc", type=int, default=MIN_PROC)
    ap.add_argument("--min-occ", type=int, default=MIN_OCC)
    ap.add_argument("--persist", action="store_true", help="записать кандидатов в DI")
    ap.add_argument("--out", default="/tmp/miner_v2_report.json")
    args = ap.parse_args()

    occ = Counter()
    procs = defaultdict(set)
    clusters = defaultdict(set)
    meta = {}
    rows_scanned = 0

    conn = _connect_di()
    conn.set_session(readonly=True, autocommit=False)
    cur = conn.cursor(name="miner_v2")
    cur.itersize = 20000
    cur.execute("""
        SELECT d.id, m.procurement_id, d.row_data, d.matched_text,
               d.context_before, d.context_after, d.category_code
          FROM document_match_details d
          JOIN document_matches m ON m.id = d.match_id
         WHERE d.row_data IS NOT NULL AND d.row_data::text <> '{}'
         ORDER BY d.id DESC LIMIT %s
    """, (args.limit,))

    for detail_id, pid, row_data, matched_text, ctx_b, ctx_a, category in cur:
        rows_scanned += 1
        if rows_scanned % 50000 == 0:
            print("PROGRESS", rows_scanned, len(occ), flush=True)
        for fragment in fragments(row_data, matched_text):
            if len(fragment) > 200:
                continue
            # Единица измерения ищется по всей строке-фрагменту, а не по обрывку:
            # «Листы гипсокартонные ГКЛО | м2» — товар с единицей.
            row_has_unit = _has_unit(fragment)
            for chunk in _SPLIT.split(fragment):
                tokens = canonical_tokens(chunk)
                if len(tokens) < 2 or len(tokens) > 30:
                    continue
                for size in (2, 3):
                    for i in range(len(tokens) - size + 1):
                        window = tokens[i:i + size]
                        bucket = classify_window(window)
                        if not bucket:
                            continue
                        if bucket == "CATEGORY_CANDIDATE" and not row_has_unit:
                            continue
                        phrase = " ".join(window)
                        if len(phrase) < 8:
                            continue
                        if _is_header_noise(phrase):
                            continue
                        if bucket == "CATEGORY_CANDIDATE" and _is_non_product(phrase):
                            continue
                        key = (bucket, phrase)
                        occ[key] += 1
                        procs[key].add(pid)
                        if key not in meta:
                            meta[key] = {
                                "example_quote": chunk.strip()[:300],
                                "context": " ".join(
                                    [str(x) for x in (ctx_b or [])][-2:] +
                                    [chunk.strip()] +
                                    [str(x) for x in (ctx_a or [])][:2])[:400],
                                "detail_id": detail_id,
                                "procurement_id": pid,
                                "category_code": category,
                            }
    conn.close()
    print("ROWS_SCANNED", rows_scanned, flush=True)

    # --- OKPD-кластеры: честный подсчёт по коду ОКПД закупки ---
    pid_cluster = {}
    all_pids = sorted({p for s in procs.values() for p in s})
    if all_pids:
        crm = psycopg2.connect(**require_crm_db_connect_kwargs())
        cc = crm.cursor()
        cc.execute("SELECT id, okpd_code FROM crm_procurements WHERE id = ANY(%s)", (all_pids,))
        for pid, code in cc.fetchall():
            pid_cluster[int(pid)] = okpd_cluster(code)
        crm.close()
    for key, pset in procs.items():
        clusters[key] = {pid_cluster.get(p, "UNKNOWN") for p in pset}

    passing = {}
    for key, n in occ.items():
        if n >= args.min_occ and len(procs[key]) >= args.min_proc:
            passing[key] = n

    by_bucket = Counter(k[0] for k in occ)
    pass_bucket = Counter(k[0] for k in passing)
    cluster_hist = Counter()
    for key in passing:
        for cl in clusters[key]:
            cluster_hist[cl] += 1

    top_cat = sorted([k for k in passing if k[0] == "CATEGORY_CANDIDATE"],
                     key=lambda k: (-len(procs[k]), -occ[k]))[:25]
    top_tech = sorted([k for k in passing if k[0] == "TECHNICAL_ATTRIBUTE_CANDIDATE"],
                      key=lambda k: (-len(procs[k]), -occ[k]))[:25]

    print("CATEGORY_CANDIDATES", by_bucket["CATEGORY_CANDIDATE"])
    print("TECH_ATTRIBUTE_CANDIDATES", by_bucket["TECHNICAL_ATTRIBUTE_CANDIDATE"])
    print("CATEGORY_CANDIDATES_5PROC_8OCC", pass_bucket["CATEGORY_CANDIDATE"])
    print("TECH_ATTRIBUTE_CANDIDATES_5PROC_8OCC", pass_bucket["TECHNICAL_ATTRIBUTE_CANDIDATE"])
    print("BY_OKPD_CLUSTER", json.dumps(cluster_hist.most_common(15), ensure_ascii=False))
    print("TOP_CATEGORY_CANDIDATES")
    for key in top_cat:
        print("   %3d proc %4d occ %-12s | %s" % (len(procs[key]), occ[key],
                                                  sorted(clusters[key])[:2], key[1]))
    print("TOP_TECH_ATTRIBUTES")
    for key in top_tech:
        p, v, u = split_param_value_unit(key[1].split())
        print("   %3d proc %4d occ | param=%-22s value=%-10s unit=%-6s" %
              (len(procs[key]), occ[key], p[:22], str(v)[:10], str(u)[:6]))

    def show(prefixes, title):
        print(title)
        for key, n in sorted(occ.items(), key=lambda kv: -kv[1]):
            phrase = key[1]
            if not any(phrase.startswith(p) for p in prefixes):
                continue
            p, v, u = split_param_value_unit(phrase.split())
            print("   %-6s %3d proc %4d occ | %-34s | value=%-8s unit=%-5s" %
                  (key[0][:6], len(procs[key]), n, phrase[:34], str(v)[:8], str(u)[:5]))
            print("      quote:", meta[key]["example_quote"][:110])

    show(("гипсокартон", "гкл"), "DRYWALL_CANDIDATES")
    show(("толщин", "класс пожарн", "класс примен", "класс 3", "класс 4"), "TECH_EXAMPLES")

    report = {
        "rows_scanned": rows_scanned,
        "category_candidates": by_bucket["CATEGORY_CANDIDATE"],
        "tech_attribute_candidates": by_bucket["TECHNICAL_ATTRIBUTE_CANDIDATE"],
        "category_candidates_5proc_8occ": pass_bucket["CATEGORY_CANDIDATE"],
        "tech_attribute_candidates_5proc_8occ": pass_bucket["TECHNICAL_ATTRIBUTE_CANDIDATE"],
        "by_okpd_cluster": cluster_hist.most_common(50),
        "top_category_candidates": [
            {"phrase": k[1], "occ": occ[k], "procs": len(procs[k]),
             "clusters": sorted(clusters[k])[:5], "quote": meta[k]["example_quote"]}
            for k in top_cat],
        "top_tech_attributes": [
            {"phrase": k[1], "occ": occ[k], "procs": len(procs[k]), "clusters": sorted(clusters[k])[:5],
             "param": split_param_value_unit(k[1].split())[0],
             "value": split_param_value_unit(k[1].split())[1],
             "unit": split_param_value_unit(k[1].split())[2],
             "quote": meta[k]["example_quote"], "provenance": meta[k]}
            for k in top_tech],
        "crm_writes": 0,
        "queue_writes": 0,
        "http_requests": 0,
        "candidates": [
            {"phrase": k[1], "bucket": k[0], "occ": occ[k], "procs": len(procs[k]),
             "clusters": sorted(clusters[k])[:8],
             "param": split_param_value_unit(k[1].split())[0],
             "value": split_param_value_unit(k[1].split())[1],
             "unit": split_param_value_unit(k[1].split())[2],
             "quote": meta[k]["example_quote"], "context": meta[k]["context"],
             "provenance": meta[k]}
            for k in sorted(passing, key=lambda k: (-len(procs[k]), -occ[k]))],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("REPORT_WRITTEN", args.out)

    if args.persist and passing:
        write = _connect_di()
        wc = write.cursor()
        saved = 0
        for key, n in passing.items():
            bucket, phrase = key
            p, v, u = split_param_value_unit(phrase.split())
            wc.execute("""
                INSERT INTO category_phrase_candidates
                    (phrase_normalized, bucket, occurrences, distinct_procurements,
                     distinct_okpd_clusters, param, value, unit, example_quote,
                     example_context, provenance, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'NEW')
                ON CONFLICT (phrase_normalized) DO UPDATE SET
                    occurrences = GREATEST(category_phrase_candidates.occurrences, EXCLUDED.occurrences),
                    distinct_procurements = GREATEST(category_phrase_candidates.distinct_procurements,
                                                     EXCLUDED.distinct_procurements),
                    distinct_okpd_clusters = GREATEST(category_phrase_candidates.distinct_okpd_clusters,
                                                      EXCLUDED.distinct_okpd_clusters),
                    param = EXCLUDED.param, value = EXCLUDED.value, unit = EXCLUDED.unit,
                    last_seen_at = NOW()
            """, (phrase, bucket, n, len(procs[key]), len(clusters[key]), p, v, u,
                  meta[key]["example_quote"], meta[key]["context"],
                  json.dumps(meta[key], ensure_ascii=False)))
            saved += 1
        write.commit()
        write.close()
        print("PERSISTED", saved)
    else:
        print("PERSISTED 0 (dry-run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
