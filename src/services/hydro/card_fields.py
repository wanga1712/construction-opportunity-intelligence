"""Field registry for the hydro parking/object card.

Single source of truth for three questions:
  1. what the manager sees on the card (labels, order, grouping);
  2. who owns the value — источник (автозагрузка) или менеджер (ручной ввод);
  3. which DB column the value maps to.

`ownership == OWNER_SOURCE` columns are written only by the nightly loader.
`ownership == OWNER_MANUAL` columns are never touched by the loader: the
manager's value lives in `parking_prefunnel_objects.manual_overrides`
(see `src/migrations/hydro_manual_override_1.sql`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

OWNER_SOURCE = "source"
OWNER_MANUAL = "manual"

SOURCE_LABEL = "Источник (автозагрузка)"
MANUAL_LABEL = "Поле менеджера (ручной ввод)"


@dataclass(frozen=True)
class HydroField:
    """One card field with provenance."""

    key: str
    label: str
    ownership: str = OWNER_MANUAL
    kind: str = "text"  # text | money | date | flag | badge | list | url
    choices: tuple[str, ...] = ()
    choice_labels: dict[str, str] = field(default_factory=dict)
    hint: str = ""

    @property
    def is_manual(self) -> bool:
        return self.ownership == OWNER_MANUAL


@dataclass(frozen=True)
class HydroFieldGroup:
    """One titled block inside a section (Дефектовка, КП, Торги 615-ПП, ...)."""

    key: str
    title: str
    fields: tuple[HydroField, ...]
    hint: str = ""


@dataclass(frozen=True)
class HydroSection:
    key: str
    title: str
    groups: tuple[HydroFieldGroup, ...]


ACCESS_STATUS = HydroField(
    key="access_status", label="Статус доступа", kind="badge",
    choices=("pending", "granted", "rejected"),
    choice_labels={"pending": "Не получен", "granted": "Получен", "rejected": "Отказ"},
)
SEVERITY = HydroField(
    key="severity", label="Критичность дефектов", kind="badge",
    choices=("critical", "medium", "minor"),
    choice_labels={"critical": "Критично", "medium": "Средне", "minor": "Незначительно"},
)
PROPOSAL_STATUS = HydroField(
    key="proposal_status", label="Статус КП", kind="badge",
    choices=("draft", "sent", "approved", "rejected"),
    choice_labels={"draft": "Черновик", "sent": "Отправлено", "approved": "Согласовано", "rejected": "Отклонено"},
)

TECH_GROUP = HydroFieldGroup(
    key="defects", title="Дефектовка",
    hint="Выезд на объект: что нашли и насколько это критично.",
    fields=(
        ACCESS_STATUS,
        HydroField(key="inspection_date", label="Дата обследования", kind="date"),
        HydroField(key="leak_types", label="Типы протечек", kind="list",
                   hint="Список через запятую: стыки, кровля, ввод, паркинг"),
        SEVERITY,
        HydroField(key="inspection_notes", label="Заключение по дефектовке", kind="text"),
        HydroField(key="inspection_photos", label="Фото обследования", kind="list"),
    ),
)
SOLUTION_GROUP = HydroFieldGroup(
    key="solution", title="Техрешение",
    fields=(
        HydroField(key="tech_solution_type", label="Тип техрешения", kind="text",
                   hint="Например: инъектирование стыков, ПВХ-мембрана, обмазочная"),
    ),
)
OFFER_GROUP = HydroFieldGroup(
    key="offer", title="КП",
    fields=(
        HydroField(key="commercial_proposal_sum", label="Сумма КП, ₽", kind="money"),
        HydroField(key="commercial_proposal_file_url", label="Файл КП", kind="url"),
        PROPOSAL_STATUS,
    ),
)
TZ_GROUP = HydroFieldGroup(
    key="tz", title="ТЗ",
    fields=(
        HydroField(key="tz_approved_by_client", label="ТЗ согласовано клиентом", kind="flag"),
        HydroField(key="tz_file_url", label="Файл ТЗ", kind="url"),
    ),
)
TENDER_GROUP = HydroFieldGroup(
    key="tender", title="Торги 615-ПП",
    fields=(
        HydroField(key="tender_number", label="Номер торгов", kind="text"),
        HydroField(key="tender_nmck", label="НМЦК, ₽", kind="money"),
        HydroField(key="tender_end_date", label="Дата окончания", kind="date"),
        HydroField(key="tender_url", label="Ссылка на торги", kind="url"),
    ),
)

SECTIONS: tuple[HydroSection, ...] = (
    HydroSection(key="tech", title="Техническое состояние", groups=(TECH_GROUP, SOLUTION_GROUP)),
    HydroSection(key="commerce", title="Коммерция", groups=(OFFER_GROUP, TZ_GROUP, TENDER_GROUP)),
)

# Секция «источник»: эти значения приходят из ночной автозагрузки NSPD.
SOURCE_GROUP = HydroFieldGroup(
    key="source", title="Карточка объекта (автозагрузка)",
    fields=(
        HydroField(key="cadastral_number", label="Кадастровый номер", ownership=OWNER_SOURCE),
        HydroField(key="address", label="Адрес", ownership=OWNER_SOURCE),
        HydroField(key="area_total", label="Площадь, м²", ownership=OWNER_SOURCE),
        HydroField(key="floors_underground", label="Подземных этажей", ownership=OWNER_SOURCE),
        HydroField(key="parking_type", label="Тип паркинга", ownership=OWNER_SOURCE),
        HydroField(key="management_status", label="Статус УК", ownership=OWNER_SOURCE),
        HydroField(key="source_updated_at", label="Обновлено в источнике", ownership=OWNER_SOURCE, kind="date"),
        HydroField(key="synced_at", label="Загружено в CRM", ownership=OWNER_SOURCE, kind="date"),
    ),
)
SOURCE_SECTION = HydroSection(key="source", title="Данные источника", groups=(SOURCE_GROUP,))


def all_fields() -> tuple[HydroField, ...]:
    fields: list[HydroField] = []
    for section in SECTIONS + (SOURCE_SECTION,):
        for group in section.groups:
            fields.extend(group.fields)
    return tuple(fields)


def manual_field_keys() -> tuple[str, ...]:
    return tuple(f.key for f in all_fields() if f.is_manual)


def source_field_keys() -> tuple[str, ...]:
    return tuple(f.key for f in all_fields() if not f.is_manual)