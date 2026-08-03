"""Сегменты и источники для вкладки «Объекты»."""

OBJECT_SEGMENT_TABS = (
    ("residential", "Жилые"),
    ("social", "Социальные"),
    ("commercial", "Коммерческие"),
    ("industrial", "Промышленные"),
    ("road_infrastructure", "Дороги / благоустройство"),
    ("other", "Прочие"),
)

OBJECT_SOURCE_OPTIONS = (
    ("nashdom", "NashDom"),
    ("44fz", "44-ФЗ"),
    ("223fz", "223-ФЗ"),
    ("615pp", "615 ПП"),
)

SOURCE_LABELS = {code: label for code, label in OBJECT_SOURCE_OPTIONS}
