"""Domain disambiguation and dual-use keyword detection for procurement prioritization.

Disambiguates keywords that appear in both target (construction/works) and non-target
(medical/electronics/food/furniture) domains, e.g. "инъекционный", "прожектор", etc.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple


# Regex patterns for domains
RE_CONSTRUCTION_KEYWORDS = re.compile(
    r"\b(ремонт\w*|строительств\w*|благоустройств\w*|монтаж\w*|кровл\w*|гидроизоляц\w*|покрыти\w*|"
    r"пол\w*|фасад\w*|шв\w*|инъектирован\w*|шпунт\w*|сва\w*|котлован\w*|бетон\w*|"
    r"асфальт\w*|дорог\w*|мост\w*|электромонтаж\w*|светильник\w*|освещени\w*|устройств\w*|"
    r"теплоснабжен\w*|водоснабжен\w*|канализац\w*|вентиляц\w*|фасадн\w*|отделочн\w*)\b",
    re.IGNORECASE,
)

RE_MEDICAL_KEYWORDS = re.compile(
    r"\b(шприц\w*|игл\w*|вакцин\w*|лекарственн\w*|медицинск\w*|препарат\w*|ампул\w*|"
    r"больниц\w*|поликлиник\w*|стоматолог\w*|хирург\w*|лаборатор\w*|реагент\w*|бинт\w*|"
    r"дезинфекц\w*|перевязочн\w*|перчатк\w*)\b",
    re.IGNORECASE,
)

RE_ELECTRONICS_IT_KEYWORDS = re.compile(
    r"\b(сервер\w*|ноутбук\w*|компьютер\w*|системный\s+блок|патч-корд\w*|коммутатор\w*|маршрутизатор\w*|"
    r"видеокарт\w*|процессор\w*|памят\w*\s+ddr|hdd|ssd|lto|мфу|картридж\w*|программн\w*\s+обеспечен\w*|"
    r"лицензи\w*|цод|виртуализац\w*)\b",
    re.IGNORECASE,
)

RE_FURNITURE_KEYWORDS = re.compile(
    r"\b(мебел\w*|стол\w*|стул\w*|кресл\w*|шкаф\w*|диван\w*|стеллаж\w*|парт\w*|тумб\w*)\b",
    re.IGNORECASE,
)

RE_FOOD_KEYWORDS = re.compile(
    r"\b(питан\w*|продукт\w*|молок\w*|хлеб\w*|мяс\w*|рыб\w*|овощ\w*|фрукт\w*|консерв\w*|круп\w*|масл\w*)\b",
    re.IGNORECASE,
)

RE_WORKS_SIGNAL = re.compile(
    r"\b(выполнени\w*|работ\w*|строительств\w*|ремонт\w*|капитальн\w*|монтаж\w*|устройств\w*|реконструкц\w*|"
    r"демонтаж\w*|инженерн\w*|прокладк\w*|реставрац\w*|обустройств\w*)\b",
    re.IGNORECASE,
)

RE_GOODS_SIGNAL = re.compile(
    r"\b(поставк\w*|закупк\w*|приобретени\w*|купля-продаж\w*|отгрузк\w*|товар\w*)\b",
    re.IGNORECASE,
)

# Contrastive dual-use patterns
RE_INJECTION_CONSTRUCTION = re.compile(
    r"\b(инъектирован\w*|инъекционн\w*\s+(?:гидроизоляц\w*|состав\w*|раствор\w*|смол\w*|пен\w*|насос\w*|пакер\w*|"
    r"укреплен\w*|бетон\w*|шов\w*|трещин\w*|грунт\w*|фундамент\w*|паркинг\w*|конструкц\w*))\b",
    re.IGNORECASE,
)

RE_INJECTION_MEDICAL = re.compile(
    r"\b(инъекционн\w*\s+(?:шприц\w*|игл\w*|раствор\w*\s+для|введени\w*|препарат\w*|форм\w*|вод\w*|лекарств\w*))\b|"
    r"\b(шприц\w*\s+инъекционн\w*|игл\w*\s+инъекционн\w*)\b",
    re.IGNORECASE,
)


def extract_domain_signals(title: str, okpd_code: str = "") -> Dict[str, float]:
    """Extracts continuous domain prior signals from title text and OKPD.

    Returns:
        dict with:
            - construction_prior: [0, 1]
            - medical_risk: [0, 1]
            - it_electronics_risk: [0, 1]
            - furniture_risk: [0, 1]
            - food_risk: [0, 1]
            - works_signal: [0, 1] (1 = works, 0 = pure goods)
            - disambiguated_injection_score: [-1, 1] (+1 = construction, -1 = medical)
    """
    text = title or ""
    okpd = (okpd_code or "").strip()
    root = okpd.split(".")[0] if "." in okpd else okpd

    # OKPD domain indicators
    is_okpd_42_43_41 = root in ("41", "42", "43")
    is_okpd_medical = root in ("21", "32") or okpd.startswith("32.50") or okpd.startswith("21.")
    is_okpd_electronics = root in ("26", "27")
    is_okpd_furniture = root == "31"
    is_okpd_food = root in ("10", "11")

    # Text keyword counts
    c_matches = len(RE_CONSTRUCTION_KEYWORDS.findall(text))
    m_matches = len(RE_MEDICAL_KEYWORDS.findall(text))
    e_matches = len(RE_ELECTRONICS_IT_KEYWORDS.findall(text))
    furn_matches = len(RE_FURNITURE_KEYWORDS.findall(text))
    food_matches = len(RE_FOOD_KEYWORDS.findall(text))

    works_matches = len(RE_WORKS_SIGNAL.findall(text))
    goods_matches = len(RE_GOODS_SIGNAL.findall(text))

    # Calculate domain priors
    c_prior = 0.0
    if is_okpd_42_43_41:
        c_prior += 0.5
    if c_matches > 0:
        c_prior += min(0.5, c_matches * 0.2)
    c_prior = min(1.0, c_prior)

    m_risk = 0.8 if is_okpd_medical else 0.0
    if m_matches > 0:
        m_risk = max(m_risk, min(1.0, m_matches * 0.35 + (0.2 if is_okpd_medical else 0.0)))

    e_risk = 0.7 if is_okpd_electronics else 0.0
    if e_matches > 0:
        e_risk = max(e_risk, min(1.0, e_matches * 0.35))

    furn_risk = 0.8 if is_okpd_furniture else 0.0
    if furn_matches > 0:
        furn_risk = max(furn_risk, min(1.0, furn_matches * 0.35))

    food_risk = 0.9 if is_okpd_food else 0.0
    if food_matches > 0:
        food_risk = max(food_risk, min(1.0, food_matches * 0.45))

    # Dual-use injection resolution
    inj_score = 0.0
    if "инъекци" in text.lower() or "инъекти" in text.lower():
        if RE_INJECTION_CONSTRUCTION.search(text) or is_okpd_42_43_41:
            inj_score = 1.0
        elif RE_INJECTION_MEDICAL.search(text) or is_okpd_medical:
            inj_score = -1.0
        else:
            if c_matches > m_matches:
                inj_score = 0.5
            elif m_matches > 0:
                inj_score = -0.8
            else:
                inj_score = -0.3

    # Works vs goods
    if works_matches > 0 and goods_matches == 0:
        works_sig = 1.0
    elif goods_matches > 0 and works_matches == 0:
        works_sig = 0.0
    elif works_matches > 0 and goods_matches > 0:
        works_sig = 0.6
    else:
        works_sig = 0.5

    return {
        "construction_prior": c_prior,
        "medical_risk": m_risk,
        "it_electronics_risk": e_risk,
        "furniture_risk": furn_risk,
        "food_risk": food_risk,
        "works_signal": works_sig,
        "disambiguated_injection_score": inj_score,
    }
