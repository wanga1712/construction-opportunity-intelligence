"""Stage vocabulary for the waterproofing CRM.

The direction runs on two linked funnels and they must not be merged:

* ``account`` - the managing company (УК / ГБУ) is the unit of work until a
  concrete object exists: find the УК, reach the decision maker, hold the
  meeting, get access to objects.
* ``deal`` - once a concrete address or parking exists, the unit of work is that
  object: survey, proposal, specification, procurement, contract.

Both funnels share one stage vocabulary, so a stage id always means the same
thing and a board column never mixes УК cards with object cards. Stage ids are
the stable contract (they are written into contour and deal state); Russian
labels are UI text and may change without touching stored data.

Micro-actions - first call, secretary, phone obtained, chief engineer found,
deck sent, repeat call - are deliberately *not* stages: they belong to activity,
history and next action inside the card.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FUNNEL_ACCOUNT = "account"
FUNNEL_DEAL = "deal"


@dataclass(frozen=True)
class Stage:
    """One funnel stage: stable id, UI label, owner funnel, cadence and action."""

    id: str
    label: str
    funnel: str
    description: str
    default_action: str
    touch_days: int


ACCOUNT_STAGES: tuple[Stage, ...] = (
    Stage(
        "new", "Новая УК / База", FUNNEL_ACCOUNT,
        "УК известна, работа ещё не начата",
        "Дозвониться в УК и выйти на техническую службу", 1,
    ),
    Stage(
        "meeting", "Назначение встречи", FUNNEL_ACCOUNT,
        "Идёт выход на ЛПР и согласование встречи",
        "Согласовать встречу по портфелю подземных помещений", 2,
    ),
    Stage(
        "followup", "Встреча / Дожим", FUNNEL_ACCOUNT,
        "Встреча прошла или срывается, нужен дожим",
        "Зафиксировать результат встречи и договориться о следующем шаге", 3,
    ),
    Stage(
        "survey_approved", "Доступ к объектам", FUNNEL_ACCOUNT,
        "Согласованы объекты и доступ для обследования",
        "Получить доступ и назначить дату выезда", 3,
    ),
)

DEAL_STAGES: tuple[Stage, ...] = (
    Stage(
        "survey", "Обследование", FUNNEL_DEAL,
        "Выезд, дефектовка и фотофиксация объекта",
        "Зафиксировать дефекты, фото и типы протечек", 5,
    ),
    Stage(
        "proposal", "КП / Техрешение", FUNNEL_DEAL,
        "Готовится и защищается КП с техническим решением",
        "Подготовить КП и защитить техническое решение", 5,
    ),
    Stage(
        "specification", "Подготовка ТЗ", FUNNEL_DEAL,
        "Заказчик готовит ТЗ под наше решение",
        "Помочь заказчику сформулировать ТЗ", 7,
    ),
    Stage(
        "procurement", "Торги / Закупка", FUNNEL_DEAL,
        "Закупка объявлена, идут торги",
        "Проконтролировать торги и уточнить сроки договора", 7,
    ),
    Stage(
        "contract", "Контракт / Работы", FUNNEL_DEAL,
        "Контракт подписан, объект передан в работы",
        "Согласовать график работ и передать объект производству", 10,
    ),
)

# Contours put aside keep their saved state instead of being deleted or dropped
# back into the first column.
CLOSED_STAGE = Stage(
    "closed", "Отложено / отказ", FUNNEL_ACCOUNT,
    "Работа приостановлена", "Назначить касание для возврата к УК", 30,
)

ALL_STAGES: tuple[Stage, ...] = ACCOUNT_STAGES + DEAL_STAGES + (CLOSED_STAGE,)
FUNNELS: dict[str, tuple[Stage, ...]] = {
    FUNNEL_ACCOUNT: ACCOUNT_STAGES,
    FUNNEL_DEAL: DEAL_STAGES,
}
FUNNEL_LABELS: dict[str, str] = {
    FUNNEL_ACCOUNT: "Воронка УК",
    FUNNEL_DEAL: "Воронка объектов",
}

STAGE_IDS: tuple[str, ...] = tuple(stage.id for stage in ALL_STAGES)
ACCOUNT_STAGE_IDS: tuple[str, ...] = tuple(stage.id for stage in ACCOUNT_STAGES)
DEAL_STAGE_IDS: tuple[str, ...] = tuple(stage.id for stage in DEAL_STAGES)

STAGE_LABELS: dict[str, str] = {stage.id: stage.label for stage in ALL_STAGES}
STAGE_FUNNEL: dict[str, str] = {stage.id: stage.funnel for stage in ALL_STAGES}
STAGE_DESCRIPTIONS: dict[str, str] = {stage.id: stage.description for stage in ALL_STAGES}
STAGE_DEFAULT_ACTIONS: dict[str, str] = {stage.id: stage.default_action for stage in ALL_STAGES}
STAGE_TOUCH_DAYS: dict[str, int] = {stage.id: stage.touch_days for stage in ALL_STAGES}

# Stage names written by earlier funnel versions must keep resolving, otherwise
# saved contours would silently restart from the first column.
LEGACY_STAGE_ALIASES: dict[str, str] = {
    # Previous single-board УК funnel (11 columns).
    "УК найдена": "new",
    "Первичный звонок": "new",
    "Секретарь / диспетчер": "new",
    "Найден тех. контакт": "meeting",
    "Встреча назначена": "meeting",
    "Обследование назначено": "survey_approved",
    "Обследование проведено": "survey",
    "КП / техрешение": "proposal",
    "Согласование / ТЗ / торги": "specification",
    "Договор / работы": "contract",
    "Отложено / отказ": "closed",
    # Object-centric contour that predates the УК funnel.
    "Контур найден": "new",
    "Секретарь / общий телефон найден": "new",
    "Запрошен начальник эксплуатации": "new",
    "Контакт эксплуатации получен": "meeting",
    "Первая встреча проведена": "followup",
    "Выбран объект для обследования": "survey_approved",
    "Сделка / ТКП по объекту": "proposal",
}

# A stage saved for the *other* funnel must never drop a card back to the start:
# an УК contour that already reached an object stage has objectively given access
# to objects, and an object deal saved at an УК stage has not been surveyed yet.
_FOREIGN_STAGE: dict[tuple[str, str], str] = {
    (FUNNEL_ACCOUNT, "survey"): "survey_approved",
    (FUNNEL_ACCOUNT, "proposal"): "survey_approved",
    (FUNNEL_ACCOUNT, "specification"): "survey_approved",
    (FUNNEL_ACCOUNT, "procurement"): "survey_approved",
    (FUNNEL_ACCOUNT, "contract"): "survey_approved",
    (FUNNEL_DEAL, "new"): "survey",
    (FUNNEL_DEAL, "meeting"): "survey",
    (FUNNEL_DEAL, "followup"): "survey",
    (FUNNEL_DEAL, "survey_approved"): "survey",
}

_LABEL_TO_ID: dict[str, str] = {stage.label: stage.id for stage in ALL_STAGES}


def funnel_stages(funnel: str) -> tuple[Stage, ...]:
    """Stages of one funnel in board order."""
    return FUNNELS.get(funnel) or ACCOUNT_STAGES


def _funnel_start(funnel: str) -> str:
    return funnel_stages(funnel)[0].id


def normalize_stage(value: Any, *, funnel: str | None = None) -> str:
    """Return a canonical stage id; unknown values fall back to the funnel start."""
    text = str(value or "").strip()
    if text in STAGE_IDS:
        return text
    if text in _LABEL_TO_ID:
        return _LABEL_TO_ID[text]
    alias = LEGACY_STAGE_ALIASES.get(text)
    if alias:
        return alias
    return _funnel_start(funnel or FUNNEL_ACCOUNT)


def coerce_stage(value: Any, funnel: str) -> str:
    """Canonical stage id guaranteed to belong to the given funnel."""
    stage = normalize_stage(value, funnel=funnel)
    if stage in {item.id for item in funnel_stages(funnel)}:
        return stage
    if funnel == FUNNEL_ACCOUNT and stage == CLOSED_STAGE.id:
        return stage
    return _FOREIGN_STAGE.get((funnel, stage), _funnel_start(funnel))


def stage_label(value: Any) -> str:
    """Russian UI label for a stage value."""
    return STAGE_LABELS.get(normalize_stage(value), str(value or ""))


def stage_funnel(value: Any) -> str:
    """Owner funnel of a stage value."""
    return STAGE_FUNNEL.get(normalize_stage(value), FUNNEL_ACCOUNT)


def stage_index(value: Any, funnel: str = FUNNEL_ACCOUNT) -> int:
    """Zero-based board position inside a funnel; closed sits past the board."""
    ids = tuple(item.id for item in funnel_stages(funnel))
    stage = normalize_stage(value, funnel=funnel)
    return ids.index(stage) if stage in ids else len(ids)


def is_closed_stage(value: Any) -> bool:
    """Whether a contour was put aside."""
    return normalize_stage(value) == CLOSED_STAGE.id


def board_columns(funnel: str) -> list[dict[str, Any]]:
    """Empty column skeletons of one funnel, ready for grouping cards."""
    return [
        {
            "stage": stage.id,
            "label": stage.label,
            "description": stage.description,
            "index": index,
            "count": 0,
            "cards": [],
        }
        for index, stage in enumerate(funnel_stages(funnel))
    ]


__all__ = [
    "ACCOUNT_STAGES",
    "ACCOUNT_STAGE_IDS",
    "ALL_STAGES",
    "CLOSED_STAGE",
    "DEAL_STAGES",
    "DEAL_STAGE_IDS",
    "FUNNELS",
    "FUNNEL_ACCOUNT",
    "FUNNEL_DEAL",
    "FUNNEL_LABELS",
    "LEGACY_STAGE_ALIASES",
    "STAGE_DEFAULT_ACTIONS",
    "STAGE_DESCRIPTIONS",
    "STAGE_FUNNEL",
    "STAGE_IDS",
    "STAGE_LABELS",
    "STAGE_TOUCH_DAYS",
    "Stage",
    "board_columns",
    "coerce_stage",
    "funnel_stages",
    "is_closed_stage",
    "normalize_stage",
    "stage_funnel",
    "stage_index",
    "stage_label",
]
