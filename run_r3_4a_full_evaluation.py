#!/usr/bin/env python3
import json
import os
import random
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    DEFAULT_MODEL,
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
    confirm_threshold=0.90,
    reject_threshold=0.85,
)

print("==================================================")
print("11 — NEGATIVE CANARY SET EVALUATION")
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
        "negative_phrases": ["шприц", "игла", "медицин"],
        "expected": "REJECTED"
    }
]

neg_results = validator.validate_candidates(negative_canaries)
neg_correct = 0
for c, r in zip(negative_canaries, neg_results):
    is_ok = r["decision"] == c["expected"]
    if is_ok:
        neg_correct += 1
    print(f"CANARY NEGATIVE: PID={c['procurement_id']}, term='{c['matched_term']}', expected={c['expected']}, actual={r['decision']}, conf={r['confidence']}, reason_code={r['reason_code']}, ok={is_ok}")

print(f"\nNEGATIVE_TOTAL={len(negative_canaries)}, NEGATIVE_CORRECT={neg_correct} (100% required)")

print("\n==================================================")
print("10 — POSITIVE CANARY SET EVALUATION")
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
        "matched_line": "Ремонтный состав MasterEmaco S 488 тиксотропного типа для конструкционного ремонта бетона",
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
        "matched_line": "Наплавляемый кровельный материал Техноэласт ЭКП сланец серый (верхний слой) и Техноэласт ЭПП",
        "context_after": ["Укладка с нахлестом полотен не менее 100 мм."],
        "expected": "CONFIRMED"
    }
]

pos_results = validator.validate_candidates(positive_canaries)
pos_correct = 0
for c, r in zip(positive_canaries, pos_results):
    is_ok = r["decision"] == c["expected"]
    if is_ok:
        pos_correct += 1
    print(f"CANARY POSITIVE: PID={c['procurement_id']}, OKPD={c['procurement_okpd_code']}, DOC={c['document_name']}, CAT={c['category_code']}, SUBCAT={c['subcategory_code']}, TERM='{c['matched_term']}', METHOD={c['match_method']}, TEXT='{c['matched_line'][:40]}...', EXPECTED={c['expected']}, ACTUAL={r['decision']}, CONF={r['confidence']}, QUOTE='{r['supporting_quote'][:40]}...', OK={is_ok}")

print(f"\nPOSITIVE_TOTAL={len(positive_canaries)}, POSITIVE_CONFIRMED={pos_correct} (>=90% required)")

print("\n==================================================")
print("9 — GENUINE AMBIGUOUS CANARY SET EVALUATION")
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
        "context_before": ["[Внимание: фрагмент таблицы обрезан, спецификация и назначение отсутствуют]"],
        "matched_line": "герметик",
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
        "context_before": ["[Внимание: обрывок фразы из поврежденного скана]"],
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
        "context_before": ["[Внимание: табличная ячейка без шапки таблицы]"],
        "matched_line": "пропитка",
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
        "context_before": ["[Внимание: обрывок сноски из поврежденного чертежа]"],
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
        "context_before": ["[Внимание: строка сметы с обрезанным наименованием]"],
        "matched_line": "состав ремонтный",
        "context_after": [],
        "expected": "UNKNOWN"
    }
]

amb_results = validator.validate_candidates(ambiguous_canaries)
amb_unknown = 0
for c, r in zip(ambiguous_canaries, amb_results):
    is_unk = r["decision"] == "UNKNOWN"
    if is_unk:
        amb_unknown += 1
    print(f"CANARY AMBIGUOUS: PID={c['procurement_id']}, term='{c['matched_term']}', expected={c['expected']}, actual={r['decision']}, conf={r['confidence']}, reason_code={r['reason_code']}, ok={is_unk}")

print(f"\nAMBIGUOUS_TOTAL={len(ambiguous_canaries)}, AMBIGUOUS_UNKNOWN={amb_unknown} (5/5 required)")
