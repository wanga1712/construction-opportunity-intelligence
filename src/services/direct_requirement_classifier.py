"""Классификация извлечённых данных прямой поставки по разделам карточки.

Одна исходная запись — один основной раздел (ESTIMATE / PRODUCT_REQUIREMENT /
DELIVERY_REQUIREMENT / PARTICIPANT_REQUIREMENT / SECURITY_REQUIREMENT /
ADDITIONAL_REQUIREMENT / UNCLASSIFIED). Исходный текст, файл-источник и исходный
ключ раздела сохраняются, поэтому ничего не теряется и всё прослеживается.

Скоринг/медали/lifecycle не затрагиваются: модуль только читает extraction dict
из direct_document_extractor и dossier из CRM.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

SECTIONS = ("estimate", "product", "delivery", "participant", "security",
            "national", "additional", "unclassified")

#: Коммерческий режим: подтверждённый источник — scope gate, затем трек возможностей.
DIRECT_SCOPE_TYPES = ("DIRECT_GOODS",)
DIRECT_TRACKS = ("DIRECT_SUPPLY",)
DIRECT_FORMS = ("DIRECT_GOODS_PURCHASE",)
DIRECT_ANALYSIS_MODES = ("DIRECT_PRODUCT",)

_DELIVERY_MARKERS = (
    "срок поставки", "сроки поставки", "поставка осуществляется", "поставка товара",
    "место доставки", "адрес поставки", "доставка", "отгрузк", "упаковк", "тара",
    "транспортиров", "монтаж", "наладк", "ввод в эксплуатац", "приемк", "приёмк",
    "гарантийн", "гарантия", "сопроводительн", "паспорт товара", "инструкци",
    "сертификат соответствия", "маркировк", "погрузочно-разгрузочн", "разгрузк",
)
_PARTICIPANT_MARKERS = (
    "участник", "участников", "заявк", "лиценз", "сро", "опыт", "квалификац",
    "рнп", "реестр недобросовестн", "декларац", "соответствие требован",
    "не привлекал", "административн", "налог", "аффилирован", "сговор",
    "оператор электронной площадки", "переговор", "аукцион", "оформлени",
    "содержанию, форме", "составу заявки", "заявка на участие",
)
_SECURITY_MARKERS = (
    "обеспечение", "независимая гарантия", "банковская гарантия", "обеспечительн",
    "залог", "поручительств", "возврат обеспечен", "размер обеспечен",
)
#: Национальный режим и происхождение товара — отдельный раздел, не «дополнительно».
_NATIONAL_MARKERS = (
    "страна происхождения", "национальн", "преференц", "евразийск", "постановлени",
    "реестров", "радиоэлектронной продукции", "промышленной продукции",
    "уровень радиоэлектронной", "совокупном количестве баллов", "балл",
    "запрет", "ограничен", "закупк", "ст-1", "приложение к постановлению",
)
_ADDITIONAL_MARKERS = (
    "штраф", "пеня", "ответственност", "расторжен", "неустойк", "оплат",
    "расчет", "расчёт", "аванс", "цена договора", "цена контракта",
    "форс-мажор", "обстоятельств непреодолимой силы", "конфиденциальн",
    "антидемпинг",
)
#: Группы технических требований: ключ -> подписи.
PRODUCT_GROUPS = (
    ("processor", "Процессор и вычисления",
     ("процессор", "ядр", "тактов", "частот", "cpu", "виртуализац", "вычислен")),
    ("memory", "Оперативная память", ("оперативн", "озу", "память", "ddr", "модул")),
    ("storage", "Хранение данных",
     ("накопител", "диск", "ssd", "hdd", "raid", "lff", "sff", "хранилищ", "массив")),
    ("network", "Сетевые интерфейсы",
     ("сетев", "ethernet", "порт", "sfp", "интерфейс", "10gbe", "1gbe", "lan", "порт")),
    ("chassis", "Корпус и охлаждение",
     ("корпус", "стоечн", "rack", "охлажд", "вентилятор", "блок питания", "питани",
      "направляющ", "кабел", "слот")),
    ("management", "Управление и ПО",
     ("управлен", "мониторинг", "ipmi", "bmc", "прошивк", "операционн", "программн",
      "лицензи", "контроллер")),
    ("reliability", "Надёжность и совместимость",
     ("надежн", "надёжн", "резервирован", "ошибк", "ecc", "совместим", "отказоустойчив",
      "бесперебойн")),
    ("other", "Прочие характеристики товара", ()),
)


def direct_mode(dossier: Dict[str, Any]) -> Dict[str, Any]:
    """Прямая поставка? Источник решения — scope authority, затем трек возможности."""
    scope = (dossier or {}).get("scope") or {}
    scope_type = str(scope.get("procurement_scope_type") or "").upper()
    if scope_type in DIRECT_SCOPE_TYPES:
        return {"is_direct": True, "source": "scope_authority", "scope_type": scope_type,
                "confidence": scope.get("scope_confidence"),
                "method": scope.get("scope_method"), "version": scope.get("scope_version")}
    opportunities = (dossier or {}).get("opportunities") or []
    for item in opportunities:
        if str(item.get("opportunity_track") or "").upper() in DIRECT_TRACKS:
            return {"is_direct": True, "source": "opportunity_track",
                    "scope_type": scope_type or None,
                    "form": item.get("procurement_form"),
                    "analysis_mode": item.get("analysis_mode")}
    for item in opportunities:
        if str(item.get("procurement_form") or "").upper() in DIRECT_FORMS or \
                str(item.get("analysis_mode") or "").upper() in DIRECT_ANALYSIS_MODES:
            return {"is_direct": True, "source": "opportunity_form",
                    "form": item.get("procurement_form"),
                    "analysis_mode": item.get("analysis_mode")}
    return {"is_direct": False, "source": "none", "scope_type": scope_type or None}


def _squash(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_text(value: Any) -> str:
    """Аккуратная нормализация текста требования (без изменения смысла)."""
    text = _norm(value)
    text = re.sub(r"\b0{5,}\d*\b", " ", text)          # служебные нумера вида 00000000000000000510
    text = re.sub(r"([.…])[.…\s]{2,}", r"\1 ", text)   # многоточия-заполнители
    text = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", text)  # «26. 20.14.1 20» → «26.20.14.120»
    text = re.sub(r"^\s*[\d]+(?:\s*[.)]\s*\d*)*\s*[.)]?\s*", "", text)  # ведущая нумерация
    text = re.sub(r"\s+([,;:)])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip(" .;")


def _is_noise(text: str) -> bool:
    """Осколок таблицы, колонка-число или заголовок без требования."""
    value = str(text or "").strip()
    letters = len(re.findall(r"[A-Za-zА-Яа-яЁё]", value))
    if letters < 4:
        return True
    if value.count(".") + value.count("…") > max(6, len(value) // 4):
        return True
    words = value.split()
    if len(value) < 60 and not re.search(r"\d", value) and len(words) <= 7 \
            and not re.search(r"должен|не допускается|обяз|требует|вправе|запрещ", value, re.I):
        return True
    return False


def _hits(text: str, markers) -> int:
    low = str(text or "").lower()
    return sum(1 for marker in markers if marker in low)


def _mandatory(text: str) -> Optional[bool]:
    """Признак обязательности — только если он прямо указан в тексте."""
    low = str(text or "").lower()
    if any(marker in low for marker in ("не допускается", "обязательн", "должен соответств",
                                        "требуется", "обязан ")):
        return True
    if any(marker in low for marker in ("рекомендуем", "дополнительн", "по желанию",
                                        "не является обязательным")):
        return False
    return None


def _classify_text(text: str) -> str:
    """Детерминированное отнесение текста требования к основному разделу."""
    national = _hits(text, _NATIONAL_MARKERS)
    security = _hits(text, _SECURITY_MARKERS)
    delivery = _hits(text, _DELIVERY_MARKERS)
    participant = _hits(text, _PARTICIPANT_MARKERS)
    additional = _hits(text, _ADDITIONAL_MARKERS)
    best = max(national, security, delivery, participant, additional)
    if best == 0:
        return "unclassified"
    if national == best:
        return "national"
    if security == best:
        return "security"
    if delivery == best:
        return "delivery"
    if participant == best:
        return "participant"
    return "additional"


def product_group(text: str) -> str:
    low = str(text or "").lower()
    for key, _title, markers in PRODUCT_GROUPS:
        if markers and any(marker in low for marker in markers):
            return key
    return "other"


def _tech_record(row: Dict[str, Any], index: int) -> Dict[str, Any]:
    cells = [_norm(c) for c in (row.get("cells") or [])]
    param = cells[0] if cells else ""
    value = cells[1] if len(cells) > 1 else ""
    unit = cells[2] if len(cells) > 2 else ""
    return {
        "id": "tech:%d" % index,
        "section": "product",
        "source": "tech",
        "source_file": row.get("source_file"),
        "param": param or value,
        "value": value if param else "",
        "unit": unit,
        "text": _norm(" | ".join(c for c in cells if c))[:400],
        "group": product_group(param or value),
        "mandatory": _mandatory(param or value),
    }


def _section_record(item: Dict[str, Any], source: str, index: int,
                    forced: Optional[str] = None) -> Dict[str, Any]:
    raw = _norm(item.get("text"))
    text = clean_text(raw)
    return {
        "id": "%s:%d" % (source, index),
        "section": forced or _classify_text(text or raw),
        "source": source,
        "source_file": item.get("source_file"),
        "text": (text or raw)[:600],
        "noise": _is_noise(text or raw),
        "param": None,
        "value": None,
        "unit": None,
        "group": None,
        "mandatory": _mandatory(text),
    }


def classify(extraction: Dict[str, Any], dossier: Dict[str, Any]) -> Dict[str, Any]:
    """Разложить extraction по разделам карточки с полной трассировкой."""
    buckets: Dict[str, List[Dict[str, Any]]] = {key: [] for key in SECTIONS}
    audit: Dict[str, Any] = {"by_source": {}, "input_total": 0, "output_total": 0}

    def add(record: Dict[str, Any]) -> None:
        buckets[record["section"] if record["section"] in buckets else "unclassified"].append(record)

    for index, row in enumerate(extraction.get("spec") or []):
        cells = [_norm(c) for c in (row.get("cells") or [])]
        add({"id": "est:%d" % index, "section": "estimate", "source": "spec",
             "source_file": row.get("source_file"), "text": _norm(" | ".join(cells))[:400],
             "param": None, "value": None, "unit": None, "group": None,
             "mandatory": None})
    for index, row in enumerate(extraction.get("tech") or []):
        add(_tech_record(row, index))
    for index, row in enumerate(extraction.get("requirements") or []):
        raw = _norm(" | ".join(c for c in (row.get("cells") or []) if _norm(c)))
        text = clean_text(raw)
        noise = _is_noise(text or raw)
        add({"id": "req:%d" % index,
             "section": "unclassified" if noise else _classify_text(text or raw),
             "source": "requirements", "source_file": row.get("source_file"),
             "text": (text or raw)[:600], "noise": noise, "param": None,
             "value": None, "unit": None, "group": None,
             "mandatory": None if noise else _mandatory(text or raw)})
    forced_map = {"participant": "participant", "participation": "participant",
                  "security": "security", "national": "national"}
    for key, items in (extraction.get("sections") or {}).items():
        for index, item in enumerate(items or []):
            text = _norm(item.get("text"))
            # Секция «требования к товару» по умолчанию товарная: её текст собран по
            # подписям «технические требования / требования к товару», а не по словам.
            if key == "product":
                cleaned = clean_text(text)
                if _is_noise(cleaned):
                    forced = "unclassified"
                elif _hits(cleaned, _NATIONAL_MARKERS):
                    forced = "national"
                elif _hits(cleaned, _DELIVERY_MARKERS):
                    forced = "delivery"
                elif _hits(cleaned, _PARTICIPANT_MARKERS):
                    forced = "participant"
                else:
                    forced = "product"
            else:
                forced = forced_map.get(key)
            add(_section_record(item, "sections.%s" % key, index, forced))
    for index, term in enumerate(extraction.get("terms") or []):
        add({"id": "term:%d" % index, "section": "delivery", "source": "terms",
             "source_file": term.get("source_file"), "text": _norm(term.get("text"))[:600],
             "param": "Срок поставки",
             "value": term.get("deadline") or term.get("duration_value"),
             "unit": term.get("duration_unit"),
             "group": "terms", "mandatory": None,
             "deadline": term.get("deadline"), "anchor": term.get("anchor")})

    for key, items in buckets.items():
        audit["by_source"][key] = len(items)
    audit["input_total"] = sum(audit["by_source"].values())
    audit["output_total"] = sum(len(items) for items in buckets.values())
    groups: Dict[str, int] = {}
    for record in buckets["product"]:
        groups[record.get("group") or "other"] = groups.get(record.get("group") or "other", 0) + 1
    return {
        "mode": direct_mode(dossier),
        "buckets": buckets,
        "counts": {key: len(items) for key, items in buckets.items()},
        "groups": groups,
        "group_titles": {key: title for key, title, _ in PRODUCT_GROUPS},
        "audit": audit,
    }
