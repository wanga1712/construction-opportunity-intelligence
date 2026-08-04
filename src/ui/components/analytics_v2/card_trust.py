"""Логика доверия карточки — стадии, статусы, уровни.

Медаль показывается ТОЛЬКО на стадии RANKED и выше.
До этого — КАНДИДАТ / НАЙДЕНЫ СИГНАЛЫ / КАТЕГОРИЯ ПОДТВЕРЖДЕНА.

Ключевая модель:
  opportunity_score = commercial_score * (1 - deadline_weight) + deadline_score * deadline_weight
  Уровень ограничивается сверху по deadline_ratio.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

# ── Стадии обработки ──────────────────────────────────────────────────────────

STAGE_ORDER = [
    "raw",
    "documents_loaded",
    "matches_found",
    "ai_verified",
    "ranked",
    "manager_confirmed",
]

STAGE_LABEL = {
    "raw":               "КАНДИДАТ",
    "documents_loaded":  "КАНДИДАТ",
    "matches_found":     "НАЙДЕНЫ СИГНАЛЫ",
    "ai_verified":       "КАТЕГОРИЯ ПОДТВЕРЖДЕНА",
    "ranked":            None,  # показываем медаль
    "manager_confirmed": None,  # показываем медаль + ✓
}

STAGE_DESCRIPTION = {
    "raw":               "Документы ещё не обработаны",
    "documents_loaded":  "Документы загружены, анализ ожидается",
    "matches_found":     "Найдены поисковые сигналы · категория ожидает проверки",
    "ai_verified":       "Категория подтверждена · коммерческий score не рассчитан",
    "ranked":            "Анализ завершён",
    "manager_confirmed": "Проверено менеджером",
}

# ── Базовые уровни по opportunity_score ──────────────────────────────────────
# Порядок: от высокого к низкому

LEVEL_THRESHOLDS = [
    (75, "Gold",   "#d4a017", "#d4a01718"),
    (50, "Silver", "#7c8da1", "#7c8da118"),
    (25, "Bronze", "#b36b2c", "#b36b2c18"),
    (0,  "Wood",   "#8c6b4f", "#8c6b4f18"),
]

# Максимальный уровень, разрешённый для каждого ratio-диапазона
# ratio >= 1.50 → без ограничения (Gold разрешён)
# ratio 1.00–1.49 → Gold разрешён
# ratio 0.60–0.99 → максимум Silver
# ratio 0.30–0.59 → максимум Bronze
# ratio < 0.30   → Wood
DEADLINE_CAP = [
    (1.00, None),    # нет ограничения
    (0.60, "Silver"),
    (0.30, "Bronze"),
    (0.00, "Wood"),
]

# Уровень → индекс (меньше = выше)
_LEVEL_RANK = {"Gold": 0, "Silver": 1, "Bronze": 2, "Wood": 3}

# До RANKED используем этот цвет
CANDIDATE_COLOR = ("#64748b", "#f1f5f9")


# ── Рабочие дни ───────────────────────────────────────────────────────────────

def _is_workday(d: date) -> bool:
    return d.weekday() < 5  # пн–пт


def workdays_left(end_date) -> Optional[int]:
    """Количество рабочих дней от сегодня до end_date включительно."""
    if not end_date:
        return None
    try:
        if not isinstance(end_date, date):
            from datetime import datetime
            end_date = datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date()
        today = date.today()
        if end_date < today:
            return 0
        count = 0
        cur = today
        while cur <= end_date:
            if _is_workday(cur):
                count += 1
            cur += timedelta(days=1)
        return count
    except Exception:
        return None


def days_left(end_date) -> Optional[int]:
    """Календарных дней до end_date (может быть отрицательным)."""
    if not end_date:
        return None
    try:
        if not isinstance(end_date, date):
            from datetime import datetime
            end_date = datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date()
        return (end_date - date.today()).days
    except Exception:
        return None


# ── Требуемый срок подготовки ─────────────────────────────────────────────────

def required_submission_days(price: Optional[float]) -> float:
    """
    Возвращает точное (дробное) количество необходимых рабочих дней по формуле:
      price <= 15 млн   → 2.0
      15–50 млн         → 2 + (price-15)/35 × 1.5
      50–150 млн        → 3.5 + (price-50)/100 × 1.5
      >= 150 млн        → 5.0
    """
    if price is None:
        return 3.0

    m = float(price) / 1_000_000
    if m <= 15:
        return 2.0
    if m <= 50:
        return 2.0 + (m - 15) / 35 * 1.5
    if m < 150:
        return 3.5 + (m - 50) / 100 * 1.5
    return 5.0


def required_submission_days_display(price: Optional[float]) -> int:
    """Округление вверх для отображения в UI."""
    return math.ceil(required_submission_days(price))


# ── Deadline ratio и score ────────────────────────────────────────────────────

def calc_deadline_ratio(card: dict) -> Optional[float]:
    """
    deadline_ratio = remaining_workdays / required_days.
    None если дата не известна.
    """
    wdays = workdays_left(card.get("end_date"))
    if wdays is None:
        return None
    req = required_submission_days(card.get("initial_price"))
    if req == 0:
        return 2.0
    return wdays / req


def calc_deadline_score(ratio: Optional[float]) -> int:
    """
    Deadline score из 10 баллов:
      ratio >= 1.50 → 10
      1.00–1.49     → 7
      0.60–0.99     → 4
      0.30–0.59     → 2
      < 0.30        → 0
    """
    if ratio is None:
        return 5  # неизвестно — нейтральный
    if ratio >= 1.50:
        return 10
    if ratio >= 1.00:
        return 7
    if ratio >= 0.60:
        return 4
    if ratio >= 0.30:
        return 2
    return 0


def deadline_cap_label(ratio: Optional[float]) -> Optional[str]:
    """Максимальный уровень медали, разрешённый при данном ratio. None = без ограничения."""
    if ratio is None:
        return None
    for threshold, cap in DEADLINE_CAP:
        if ratio >= threshold:
            return cap
    return "Wood"


def deadline_window_label(ratio: Optional[float]) -> str:
    """Текстовое описание коммерческого окна."""
    if ratio is None:
        return "дата окончания не указана"
    if ratio >= 1.50:
        return "комфортное"
    if ratio >= 1.00:
        return "достаточное"
    if ratio >= 0.60:
        return "недостаточное — GOLD запрещён"
    if ratio >= 0.30:
        return "окно почти закрыто — максимум BRONZE"
    return "практически закрыто"


def calc_deadline_info(card: dict) -> dict:
    """
    Возвращает полный набор данных дедлайна для отображения в карточке.
    """
    price    = card.get("initial_price")
    end_date = card.get("end_date")
    cal_days = days_left(end_date)
    wdays    = workdays_left(end_date)
    req_f    = required_submission_days(price)
    req_disp = required_submission_days_display(price)
    ratio    = calc_deadline_ratio(card)
    score    = calc_deadline_score(ratio)
    cap      = deadline_cap_label(ratio)
    window   = deadline_window_label(ratio)
    return {
        "calendar_days": cal_days,
        "workdays":      wdays,
        "required_exact": req_f,
        "required_display": req_disp,
        "ratio":         ratio,
        "deadline_score": score,
        "cap_level":     cap,    # None = без ограничения
        "window_label":  window,
    }


# ── Разрешение медали ─────────────────────────────────────────────────────────

def _apply_cap(medal: str, cap: Optional[str]) -> str:
    """Ограничивает медаль потолком cap. None = без ограничения."""
    if cap is None:
        return medal
    if _LEVEL_RANK.get(medal, 99) >= _LEVEL_RANK.get(cap, 99):
        return medal  # уже не выше потолка
    return cap


def resolve_level(card: dict) -> tuple[str, str, str, bool]:
    """
    Возвращает (display_label, color, bg, is_medal).
    is_medal=False → показывать как КАНДИДАТ, не как GOLD/SILVER.

    Логика:
    1. Медаль доступна только при processing_stage in (ranked, manager_confirmed)
    2. commercial_score должен быть задан
    3. deadline_ratio ограничивает максимальную медаль сверху
    4. remaining_workdays <= 1 → максимум Wood для любой стоимости
    """
    stage = card.get("processing_stage", "matches_found")
    manager_ok = stage == "manager_confirmed"

    if stage not in ("ranked", "manager_confirmed"):
        label = STAGE_LABEL.get(stage, "КАНДИДАТ")
        color, bg = CANDIDATE_COLOR
        return label, color, bg, False

    cscore = card.get("commercial_score")
    if cscore is None:
        return "RANKED", *CANDIDATE_COLOR, False

    # Базовая медаль по commercial_score
    base_medal = "Wood"
    base_color, base_bg = "#8c6b4f", "#8c6b4f18"
    for threshold, medal, color, bg in LEVEL_THRESHOLDS:
        if cscore >= threshold:
            base_medal, base_color, base_bg = medal, color, bg
            break

    # Deadline ratio ограничение
    wdays = workdays_left(card.get("end_date"))
    ratio = calc_deadline_ratio(card)
    cap   = deadline_cap_label(ratio)

    # Жёсткое правило: <= 1 рабочего дня → максимум Wood
    if wdays is not None and wdays <= 1:
        cap = "Wood"

    final_medal = _apply_cap(base_medal, cap)

    # Ищем цвета для финальной медали
    for _, medal, color, bg in LEVEL_THRESHOLDS:
        if medal == final_medal:
            label = final_medal + (" ✓" if manager_ok else "")
            return label, color, bg, True

    return "Wood" + (" ✓" if manager_ok else ""), "#8c6b4f", "#8c6b4f18", True


# ── Статусы подачи ────────────────────────────────────────────────────────────

def submission_status(award_status: str, end_date) -> tuple[str, str, str]:
    """Возвращает (icon, label, css_class)."""
    cal = days_left(end_date)

    if award_status == "awarded":
        return "✅", "РАЗЫГРАННЫЕ", "green"
    if award_status == "award_not_found":
        return "🔴", "РЕЗУЛЬТАТ НЕ НАЙДЕН", "red"
    if cal is None:
        return "⚪", "ДАТА НЕИЗВЕСТНА", "grey"
    if cal > 0:
        return "🟢", f"ПОДАЧА ОТКРЫТА · {cal} ДН.", "green"
    if cal == 0:
        return "🟡", "ПОДАЧА ЗАВЕРШЕНА СЕГОДНЯ · ОЖИДАЕТСЯ РЕЗУЛЬТАТ", "yellow"
    return "🟡", f"ПОДАЧА ЗАВЕРШЕНА {-cal} ДН. НАЗАД · ОЖИДАЕТСЯ РЕЗУЛЬТАТ", "yellow"


# ── Форматирование ────────────────────────────────────────────────────────────

def fmt_price(val) -> str:
    if val is None:
        return "—"
    try:
        n = float(val)
        if n >= 1e9: return f"{n/1e9:.2f} млрд ₽"
        if n >= 1e6: return f"{n/1e6:.1f} млн ₽"
        return f"{int(n):,} ₽".replace(",", " ")
    except Exception:
        return str(val)


def fmt_date(val) -> str:
    if val is None:
        return "—"
    try:
        if isinstance(val, date):
            return val.strftime("%d.%m.%Y")
        return str(val)[:10]
    except Exception:
        return str(val)


# ── Источники участников ──────────────────────────────────────────────────────

def participant_source_label(source: Optional[str], confidence: Optional[float]) -> str:
    if not source:
        return "не определён"
    labels = {
        "registry":  "подтверждён реестром закупки",
        "ai_model":  f"определён моделью · confidence {int((confidence or 0)*100)}%",
        "object_db": "найден по реестру объектов",
        "manual":    "указан менеджером",
    }
    return labels.get(source, source)


# ── Обратная совместимость (старые вызовы) ────────────────────────────────────

def required_submission_days_int(price: Optional[float]) -> int:
    return required_submission_days_display(price)


def deadline_penalty(card: dict) -> tuple[bool, int, int]:
    """Старый интерфейс: (is_expired, workdays, required_display)."""
    wdays = workdays_left(card.get("end_date")) or 0
    req   = required_submission_days_display(card.get("initial_price"))
    return wdays < req, wdays, req
