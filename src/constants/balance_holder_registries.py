"""Вкладки реестра «Балансодержатели»."""

BALANCE_HOLDER_TABS = (
    ("state", "Государственные"),
    ("commercial", "Коммерческие"),
    ("housing", "Жилищные"),
)

BALANCE_HOLDER_LABELS = {code: label for code, label in BALANCE_HOLDER_TABS}

HOUSING_SUB_TABS = (
    ("gbu_zhilischnik", "ГБУ Жилищник"),
    ("housing_commercial", "Коммерческие"),
    ("housing_noncommercial", "Некоммерческие"),
)

HOUSING_SUB_LABELS = {code: label for code, label in HOUSING_SUB_TABS}

SOURCE_TYPE = "balance_holder_segment"
