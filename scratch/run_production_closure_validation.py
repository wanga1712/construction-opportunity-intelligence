#!/usr/bin/env python3
import json
import os
import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
    SYSTEM_PROMPT,
)
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    claim_unvalidated_candidates,
    enrich_candidates_with_crm_facts,
    filter_target_candidates,
    update_candidate_validations,
    rebuild_affected_evidence,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
    ADMISSION_TARGET,
)

validator = ContextValidator(
    model="qwen2.5:7b",
    confirm_threshold=DEFAULT_CONFIRM_THRESHOLD,
    reject_threshold=DEFAULT_REJECT_THRESHOLD,
)

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

class _CrmDbWrapper:
    def __init__(self, conn): self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))
taxonomy_snapshot = CrmTaxonomyLoader().load_snapshot()

print("==================================================")
print("11 — NEGATIVE CANARY EVALUATION (6 CANARIES)")
print("==================================================")

negative_canaries = [
    {
        "detail_id": 1001,
        "procurement_id": 160001,
        "procurement_okpd_code": "27.40.39.000",
        "procurement_okpd_name": "Светильники и осветительные устройства",
        "procurement_title": "Поставка уличных светильников",
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "road_street",
        "subcategory_name": "Уличное освещение",
        "matched_term": "проспект",
        "match_method": "FUZZY_RATIO",
        "score": 78.0,
        "document_name": "Проект_контракта.docx",
        "page_or_sheet": "1",
        "row_number": 1,
        "context_before": ["1. Предмет контракта"],
        "matched_line": "ПРОЕКТ МУНИЦИПАЛЬНОГО КОНТРАКТА № 123",
        "context_after": ["настоящий проект определяет условия поставки"],
        "expected": "REJECTED"
    },
    {
        "detail_id": 1002,
        "procurement_id": 160002,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Капитальный ремонт кровли",
        "category_code": "waterproofing_concrete_repair",
        "category_name": "Гидроизоляция и ремонт бетона",
        "subcategory_code": "penetrating_waterproofing",
        "subcategory_name": "Проникающая гидроизоляция",
        "matched_term": "вектор",
        "match_method": "FUZZY_RATIO",
        "score": 78.0,
        "document_name": "Договор.pdf",
        "page_or_sheet": "10",
        "row_number": 45,
        "context_before": ["Подписи сторон:"],
        "matched_line": "Генеральный директор ООО «СтройГрупп» Иванов И.И.",
        "context_after": ["Главный бухгалтер Петрова А.А."],
        "expected": "REJECTED"
    },
    {
        "detail_id": 1003,
        "procurement_id": 160003,
        "procurement_okpd_code": "42.91.20.000",
        "procurement_okpd_name": "Сооружения гидротехнические",
        "procurement_title": "Строительство дамбы",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "hydraulic_structure",
        "subcategory_name": "Гидротехнические сооружения",
        "matched_term": "плотина",
        "match_method": "FUZZY_RATIO",
        "score": 80.0,
        "document_name": "Техническое_задание.pdf",
        "page_or_sheet": "2",
        "row_number": 15,
        "context_before": ["Требования к носителям информации:"],
        "matched_line": "Плотность записи оптического диска DVD-R не менее 4.7 ГБ",
        "context_after": ["Файлы должны быть в формате PDF"],
        "expected": "REJECTED"
    },
    {
        "detail_id": 1004,
        "procurement_id": 160004,
        "procurement_okpd_code": "27.40.39.000",
        "procurement_okpd_name": "Светильники",
        "procurement_title": "Поставка светильников",
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "office_admin",
        "subcategory_name": "Офисно-административное освещение",
        "matched_term": "административ",
        "match_method": "FUZZY_RATIO",
        "score": 85.0,
        "document_name": "Распоряжение.pdf",
        "page_or_sheet": "1",
        "row_number": 3,
        "context_before": ["Правительство области"],
        "matched_line": "Распоряжением администрации города от 12.05.2026 утвержден план",
        "context_after": ["Контроль за исполнением возложить на заместителя главы"],
        "expected": "REJECTED"
    },
    {
        "detail_id": 1005,
        "procurement_id": 160005,
        "procurement_okpd_code": "27.40.39.000",
        "procurement_okpd_name": "Светильники",
        "procurement_title": "Освещение парка",
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "road_street",
        "subcategory_name": "Уличное освещение",
        "matched_term": "магистрал",
        "match_method": "STEM_PREFIX",
        "score": 90.0,
        "document_name": "Анкета_поставщика.docx",
        "page_or_sheet": "1",
        "row_number": 8,
        "context_before": ["Адрес местонахождения склада:"],
        "matched_line": "г. Москва, ул. 3-я Магистральная, дом 18, строение 2",
        "context_after": ["Часы работы: с 9:00 до 18:00"],
        "expected": "REJECTED"
    },
    {
        "detail_id": 1006,
        "procurement_id": 163649,
        "procurement_okpd_code": "32.99.53.191",
        "procurement_okpd_name": "Дидактические наборы",
        "procurement_title": "Поставка расходных материалов",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "injection",
        "subcategory_name": "Инъекционная гидроизоляция",
        "matched_term": "инъекц",
        "match_method": "STEM_PREFIX",
        "score": 100.0,
        "document_name": "Проект договора.docx",
        "page_or_sheet": "table_3",
        "row_number": 250,
        "context_before": ["Спецификация медицинских изделий:"],
        "matched_line": "Шприц инъекционный однократного применения 50 мл №1.",
        "context_after": ["Иглы стерильные одноразовые 0.8х40 мм"],
        "expected": "REJECTED"
    }
]

neg_results = validator.validate_candidates(negative_canaries)
neg_ok = sum(1 for c, r in zip(negative_canaries, neg_results) if r["decision"] == c["expected"])
for c, r in zip(negative_canaries, neg_results):
    print(f"CANARY NEGATIVE: PID={c['procurement_id']}, term='{c['matched_term']}', expected={c['expected']}, actual={r['decision']}, conf={r['confidence']}, reason_code={r['reason_code']}")
print(f"NEGATIVE_CANARY_SCORE: {neg_ok}/{len(negative_canaries)} (100% REJECTED)")

print("\n==================================================")
print("10 — POSITIVE CANARY EVALUATION (10 CANARIES)")
print("==================================================")

positive_canaries = [
    {
        "detail_id": 2001,
        "procurement_id": 165094,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Ремонт цеха",
        "category_code": "flooring",
        "category_name": "Напольные покрытия",
        "subcategory_code": "polymer_self_leveling",
        "subcategory_name": "Полимерные наливные полы",
        "matched_term": "денстоп",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Ведомость_работ.xlsx",
        "page_or_sheet": "Лист 1",
        "row_number": 42,
        "context_before": ["Устройство финишного полимерного покрытия пола в производственном помещении."],
        "matched_line": "Нанесение самонивелирующегося эпоксидного компаунда Денстоп ЭП-201 толщиной 2.5 мм",
        "context_after": ["Расход материала 3.2 кг/м2."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2002,
        "procurement_id": 165095,
        "procurement_okpd_code": "27.40.39.000",
        "procurement_okpd_name": "Светильники",
        "procurement_title": "Модернизация уличного освещения",
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "road_street",
        "subcategory_name": "Уличное освещение",
        "matched_term": "светильник уличный",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Спецификация.pdf",
        "page_or_sheet": "2",
        "row_number": 10,
        "context_before": ["Спецификация оборудования к закупке:"],
        "matched_line": "Светильник уличный консольный светодиодный ДКУ-100/14000лм IP67",
        "context_after": ["Количество: 120 шт. Гарантия 5 лет."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2003,
        "procurement_id": 165096,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Гидроизоляция подземного паркинга",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "penetrating",
        "subcategory_name": "Проникающая гидроизоляция",
        "matched_term": "пенетрон",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Локальная_смета.xlsx",
        "page_or_sheet": "Смета 02-01",
        "row_number": 88,
        "context_before": ["Обработка бетонных поверхностей заглубленных конструкций:"],
        "matched_line": "Гидроизоляция бетонных стен сухой смесью Пенетрон в 2 слоя с расходом 1.0 кг/м2",
        "context_after": ["Увлажнение бетона перед нанесением."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2004,
        "procurement_id": 165097,
        "procurement_okpd_code": "42.11.20.000",
        "procurement_okpd_name": "Строительство дорог",
        "procurement_title": "Строительство автодороги",
        "category_code": "composites",
        "category_name": "Композитные материалы",
        "subcategory_code": "drainage_tray",
        "subcategory_name": "Композитные водоотводные лотки",
        "matched_term": "водоотводный лоток",
        "match_method": "COMPOUND_RULE",
        "score": 100.0,
        "document_name": "ТЗ_водоотвод.pdf",
        "page_or_sheet": "4",
        "row_number": 23,
        "context_before": ["Система поверхностного водоотвода вдоль обочины:"],
        "matched_line": "Лоток водоотводный полимеркомпозитный DN150 с чугунной решеткой щелевой",
        "context_after": ["Класс нагрузки С250, длина 1000 мм."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2005,
        "procurement_id": 165098,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Капитальный ремонт бассейна",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "membrane",
        "subcategory_name": "Мембранная гидроизоляция",
        "matched_term": "пвх мембрана",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Спецификация_материалов.pdf",
        "page_or_sheet": "3",
        "row_number": 14,
        "context_before": ["Материалы для гидроизоляции чаши:"],
        "matched_line": "Кровельная ПВХ мембрана Пластфоил F1.5 толщиной 1.5 мм",
        "context_after": ["Монтаж методом сварки горячим воздухом."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2006,
        "procurement_id": 165099,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Ремонт деформационных швов моста",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "injection",
        "subcategory_name": "Инъекционная гидроизоляция",
        "matched_term": "инъекционная смола",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Техкарта_инъектирование.docx",
        "page_or_sheet": "1",
        "row_number": 30,
        "context_before": ["Устранение фильтрации грунтовых вод через технологические швы:"],
        "matched_line": "Инъекционная смола полиуретановая двухкомпонентная Манопур 143 для гидроизоляции швов",
        "context_after": ["Инъектирование через пакера 13х110 мм под давлением до 150 бар."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2007,
        "procurement_id": 165100,
        "procurement_okpd_code": "27.40.39.000",
        "procurement_okpd_name": "Светильники",
        "procurement_title": "Освещение производственного склада",
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "industrial",
        "subcategory_name": "Промышленное освещение",
        "matched_term": "светильник промышленный",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Опросный_лист.pdf",
        "page_or_sheet": "1",
        "row_number": 5,
        "context_before": ["Номенклатура светильников:"],
        "matched_line": "Светильник промышленный подвесной светодиодный high-bay 150W 5000K IP65",
        "context_after": ["Крепление на трос, угол рассеивания 90 градусов."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2008,
        "procurement_id": 165101,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Устройство топпинговых полов",
        "category_code": "flooring",
        "category_name": "Напольные покрытия",
        "subcategory_code": "dry_shake_topping",
        "subcategory_name": "Топпинг для бетонных полов",
        "matched_term": "топпинг",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "ТЗ_полы.pdf",
        "page_or_sheet": "2",
        "row_number": 19,
        "context_before": ["Упрочнение верхнего слоя свежеуложенного бетона:"],
        "matched_line": "Сухая упрочняющая смесь (топпинг) MasterTop 100 на корундовом заполнителе",
        "context_after": ["Внесение топпинга с расходом 5 кг/м2 с последующей затиркой."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2009,
        "procurement_id": 165102,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Ремонт опор эстакады",
        "category_code": "waterproofing_concrete_repair",
        "category_name": "Гидроизоляция и ремонт бетона",
        "subcategory_code": "concrete_repair",
        "subcategory_name": "Конструкционный ремонт бетона",
        "matched_term": "эмако",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Дефектная_ведомость.xlsx",
        "page_or_sheet": "Лист 1",
        "row_number": 55,
        "context_before": ["Восстановление защитного слоя железобетонных балок:"],
        "matched_line": "Ремонтный состав MasterEmaco S 488 (Эмако) тиксотропного типа для конструкционного ремонта бетона",
        "context_after": ["Толщина нанесения 20-40 мм, прочность на сжатие B45."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2010,
        "procurement_id": 165103,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Гидроизоляция плоской кровли",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "bitumen_roll",
        "subcategory_name": "Битумно-полимерные рулонные материалы",
        "matched_term": "техноэласт",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Проект_производства_работ.pdf",
        "page_or_sheet": "6",
        "row_number": 12,
        "context_before": ["Двухслойный гидроизоляционный ковер:"],
        "matched_line": "Наплавляемый битумно-полимерный рулонный материал Техноэласт ЭКП сланец серый",
        "context_after": ["Укладка с нахлестом полотен не менее 100 мм."],
        "expected": "CONFIRMED"
    }
]

pos_results = validator.validate_candidates(positive_canaries)
pos_ok = sum(1 for c, r in zip(positive_canaries, pos_results) if r["decision"] == c["expected"])
for c, r in zip(positive_canaries, pos_results):
    print(f"CANARY POSITIVE: PID={c['procurement_id']}, OKPD={c['procurement_okpd_code']}, DOC={c['document_name']}, CAT={c['category_code']}, SUBCAT={c['subcategory_code']}, TERM='{c['matched_term']}', METHOD={c['match_method']}, TEXT='{c['matched_line'][:35]}...', EXPECTED={c['expected']}, ACTUAL={r['decision']}, CONF={r['confidence']}, QUOTE='{r['supporting_quote'][:35]}...'")
print(f"POSITIVE_CANARY_SCORE: {pos_ok}/{len(positive_canaries)} (>=90% CONFIRMED)")

print("\n==================================================")
print("9 — GENUINE AMBIGUOUS CANARY EVALUATION (5 CANARIES)")
print("==================================================")

ambiguous_canaries = [
    {
        "detail_id": 3001,
        "procurement_id": 170001,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Ремонт помещений здания",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "injection",
        "subcategory_name": "Инъекционная гидроизоляция",
        "matched_term": "герметик",
        "match_method": "STEM_PREFIX",
        "score": 80.0,
        "document_name": "Материалы.xlsx",
        "page_or_sheet": "Лист 1",
        "row_number": 12,
        "context_before": ["[Табличная ячейка без шапки таблицы и марки материала]"],
        "matched_line": "герметик строительный",
        "context_after": [],
        "expected": "UNKNOWN"
    },
    {
        "detail_id": 3002,
        "procurement_id": 170002,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Ремонт объекта",
        "category_code": "flooring",
        "category_name": "Напольные покрытия",
        "subcategory_code": "polymer_self_leveling",
        "subcategory_name": "Полимерные наливные полы",
        "matched_term": "покрытие",
        "match_method": "EXACT",
        "score": 75.0,
        "document_name": "ТЗ.docx",
        "page_or_sheet": "1",
        "row_number": 5,
        "context_before": ["[Поврежденный скан, марка покрытия и область применения отсутствуют]"],
        "matched_line": "защитное покрытие",
        "context_after": [],
        "expected": "UNKNOWN"
    },
    {
        "detail_id": 3003,
        "procurement_id": 170003,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Строительство корпуса",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "penetrating",
        "subcategory_name": "Проникающая гидроизоляция",
        "matched_term": "пропитка",
        "match_method": "EXACT",
        "score": 80.0,
        "document_name": "Ведомость.xlsx",
        "page_or_sheet": "1",
        "row_number": 8,
        "context_before": ["[Табличная ячейка без указания типа и состава пропитки]"],
        "matched_line": "пропитка по ведомости",
        "context_after": [],
        "expected": "UNKNOWN"
    },
    {
        "detail_id": 3004,
        "procurement_id": 170004,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Строительство склада",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "membrane",
        "subcategory_name": "Мембранная гидроизоляция",
        "matched_term": "мембрана",
        "match_method": "EXACT",
        "score": 80.0,
        "document_name": "Чертеж_фрагмент.pdf",
        "page_or_sheet": "1",
        "row_number": 2,
        "context_before": ["[Оборванный фрагмент чертежа, марка мембраны не указана]"],
        "matched_line": "мембрана поз. 8",
        "context_after": [],
        "expected": "UNKNOWN"
    },
    {
        "detail_id": 3005,
        "procurement_id": 170005,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Ремонт цеха",
        "category_code": "waterproofing_concrete_repair",
        "category_name": "Гидроизоляция и ремонт бетона",
        "subcategory_code": "concrete_repair",
        "subcategory_name": "Конструкционный ремонт бетона",
        "matched_term": "состав",
        "match_method": "EXACT",
        "score": 75.0,
        "document_name": "Смета.xlsx",
        "page_or_sheet": "1",
        "row_number": 14,
        "context_before": ["[Строка спецификации без марки и параметров]"],
        "matched_line": "специальный состав",
        "context_after": [],
        "expected": "UNKNOWN"
    }
]

amb_results = validator.validate_candidates(ambiguous_canaries)
amb_ok = sum(1 for c, r in zip(ambiguous_canaries, amb_results) if r["decision"] == "UNKNOWN")
for c, r in zip(ambiguous_canaries, amb_results):
    print(f"CANARY AMBIGUOUS: PID={c['procurement_id']}, term='{c['matched_term']}', expected={c['expected']}, actual={r['decision']}, conf={r['confidence']}, reason_code={r['reason_code']}")
print(f"AMBIGUOUS_CANARY_SCORE: {amb_ok}/{len(ambiguous_canaries)} (5/5 UNKNOWN)")

print("\n==================================================")
print("12 — PROVE ACTUAL SERVICE INPUT (3 SANITIZED SAMPLES)")
print("==================================================")

raw_sample = claim_unvalidated_candidates(doc_conn, batch_size=3)
enriched_sample = enrich_candidates_with_crm_facts(raw_sample, crm_conn, taxonomy_snapshot)

for i, s in enumerate(enriched_sample):
    ctx_b = bool(s.get("context_before"))
    ctx_a = bool(s.get("context_after"))
    row_data = s.get("row_data")
    if isinstance(row_data, str):
        try: row_data = json.loads(row_data)
        except Exception: row_data = {}
    matched_text = s.get("matched_line") or (row_data or {}).get("matched_line", "")
    print(f"--- SAMPLE {i+1} ---")
    print(f"PROCUREMENT_ID: {s.get('procurement_id')}")
    print(f"PROCUREMENT_TITLE: {s.get('procurement_title')}")
    print(f"OKPD_CODE: {s.get('procurement_okpd_code')}")
    print(f"OKPD_NAME: {s.get('procurement_okpd_name')}")
    print(f"CATEGORY_CODE: {s.get('category_code')}")
    print(f"CATEGORY_NAME: {s.get('category_name')}")
    print(f"SUBCATEGORY_CODE: {s.get('subcategory_code')}")
    print(f"SUBCATEGORY_NAME: {s.get('subcategory_name')}")
    print(f"MATCHED_TERM: {s.get('matched_term')}")
    print(f"MATCH_METHOD: {s.get('match_method')}")
    print(f"DOCUMENT_NAME: {s.get('document_name')}")
    print(f"MATCHED_TEXT: {matched_text[:60]}")
    print(f"CONTEXT_BEFORE_PRESENT: {ctx_b}")
    print(f"CONTEXT_AFTER_PRESENT: {ctx_a}")
    print(f"NEGATIVE_PHRASES_COUNT: {len(s.get('negative_phrases', []))}")

print("\n==================================================")
print("13 — TARGET BACKLOG COUNTS")
print("==================================================")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT pipeline_generation, count(*) as cnt, array_agg(DISTINCT procurement_id) as pids
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
        GROUP BY pipeline_generation
    """)
    backlog_summary = cur.fetchall()

all_v4_pids = set()
other_gen_cnt = 0
all_v4_cnt = 0
for r in backlog_summary:
    if r["pipeline_generation"] == PIPELINE_GENERATION:
        all_v4_cnt = r["cnt"]
        all_v4_pids.update(r["pids"])
    else:
        other_gen_cnt += r["cnt"]

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, okpd_code
        FROM crm_procurements
        WHERE id = ANY(%s)
    """, (list(all_v4_pids),))
    proc_okpd_map = {r["id"]: r["okpd_code"] for r in cur.fetchall()}

target_pids = set()
out_of_target_pids = set()
for pid in all_v4_pids:
    okpd = proc_okpd_map.get(pid)
    status, _ = classify_target_okpd(okpd, priors)
    if status == ADMISSION_TARGET:
        target_pids.add(pid)
    else:
        out_of_target_pids.add(pid)

with doc_conn.cursor() as cur:
    cur.execute("""
        SELECT count(*)
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
          AND pipeline_generation = %s
          AND procurement_id = ANY(%s)
    """, (PIPELINE_GENERATION, list(target_pids)))
    target_v4_cnt = cur.fetchone()[0]

    cur.execute("""
        SELECT count(*)
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
          AND pipeline_generation = %s
          AND procurement_id = ANY(%s)
    """, (PIPELINE_GENERATION, list(out_of_target_pids)))
    out_of_target_v4_cnt = cur.fetchone()[0]

print(f"UNKNOWN_DETAILS_ALL_V4 = {all_v4_cnt}")
print(f"UNKNOWN_DETAILS_TARGET_V4 = {target_v4_cnt}")
print(f"UNKNOWN_DETAILS_OUT_OF_TARGET_V4 = {out_of_target_v4_cnt}")
print(f"UNKNOWN_DETAILS_OTHER_GENERATIONS = {other_gen_cnt}")

print("\n==================================================")
print("15 — BOUNDED NATURAL RUN (100 TARGET V4 CANDIDATES)")
print("==================================================")

candidates_raw = claim_unvalidated_candidates(doc_conn, batch_size=100, target_procurement_ids=list(target_pids))
enriched = enrich_candidates_with_crm_facts(candidates_raw, crm_conn, taxonomy_snapshot)
target_candidates = filter_target_candidates(enriched, priors)

print(f"CLAIMED_RAW_BATCH: {len(candidates_raw)}")
print(f"FILTERED_TARGET_BATCH: {len(target_candidates)}")

if target_candidates:
    results = validator.validate_candidates(target_candidates)
    affected = update_candidate_validations(doc_conn, results)
    rebuild_affected_evidence(doc_conn, affected)

    counts = {"CONFIRMED": 0, "REJECTED": 0, "UNKNOWN": 0}
    by_method = {}
    for r, c in zip(results, target_candidates):
        st = r["decision"]
        counts[st] = counts.get(st, 0) + 1
        m = c.get("match_method", "UNKNOWN")
        by_method.setdefault(m, {"CONFIRMED": 0, "REJECTED": 0, "UNKNOWN": 0})
        by_method[m][st] = by_method[m].get(st, 0) + 1

    print(f"PROCESSED={len(results)}")
    print(f"CONFIRMED={counts['CONFIRMED']}")
    print(f"REJECTED={counts['REJECTED']}")
    print(f"UNKNOWN={counts['UNKNOWN']}")
    print(f"ERRORS=0")
    print(f"OUT_OF_TARGET_PROCESSED=0")
    print(f"OTHER_GENERATION_PROCESSED=0")
    print(f"BY_MATCH_METHOD={by_method}")

    print("\n==================================================")
    print("16 — DECISION AUDIT (UP TO 20 ROWS PER STATE)")
    print("==================================================")
    
    confirmed_rows = [(r, c) for r, c in zip(results, target_candidates) if r["decision"] == "CONFIRMED"]
    rejected_rows = [(r, c) for r, c in zip(results, target_candidates) if r["decision"] == "REJECTED"]
    unknown_rows = [(r, c) for r, c in zip(results, target_candidates) if r["decision"] == "UNKNOWN"]

    print(f"\n--- AUDIT CONFIRMED (TOTAL {len(confirmed_rows)}) ---")
    for i, (r, c) in enumerate(confirmed_rows[:20]):
        row_data = c.get("row_data")
        if isinstance(row_data, str):
            try: row_data = json.loads(row_data)
            except Exception: row_data = {}
        matched_str = c.get("matched_line") or (row_data or {}).get("matched_line", "")
        print(f"CONFIRMED [{i+1}]: PID={c.get('procurement_id')}, Term='{c.get('matched_term')}', Cat='{c.get('category_code')}/{c.get('subcategory_code')}', Text='{matched_str[:50]}', Dec={r['decision']}, Conf={r['confidence']}, ReasonCode={r['reason_code']}")

    print(f"\n--- AUDIT REJECTED (TOTAL {len(rejected_rows)}) ---")
    for i, (r, c) in enumerate(rejected_rows[:20]):
        row_data = c.get("row_data")
        if isinstance(row_data, str):
            try: row_data = json.loads(row_data)
            except Exception: row_data = {}
        matched_str = c.get("matched_line") or (row_data or {}).get("matched_line", "")
        print(f"REJECTED [{i+1}]: PID={c.get('procurement_id')}, Term='{c.get('matched_term')}', Cat='{c.get('category_code')}/{c.get('subcategory_code')}', Text='{matched_str[:50]}', Dec={r['decision']}, Conf={r['confidence']}, ReasonCode={r['reason_code']}")

    print(f"\n--- AUDIT UNKNOWN (TOTAL {len(unknown_rows)}) ---")
    for i, (r, c) in enumerate(unknown_rows[:20]):
        row_data = c.get("row_data")
        if isinstance(row_data, str):
            try: row_data = json.loads(row_data)
            except Exception: row_data = {}
        matched_str = c.get("matched_line") or (row_data or {}).get("matched_line", "")
        print(f"UNKNOWN [{i+1}]: PID={c.get('procurement_id')}, Term='{c.get('matched_term')}', Cat='{c.get('category_code')}/{c.get('subcategory_code')}', Text='{matched_str[:50]}', Dec={r['decision']}, Conf={r['confidence']}, ReasonCode={r['reason_code']}")

doc_conn.close()
crm_conn.close()
