# -*- coding: utf-8 -*-
"""Dwelling-purchase -> DIRECT remediation contract.

WIP=DWELLING-PURCHASE-DIRECT-REMEDIATION-V1.

Buying a finished dwelling ("приобретение/покупка/выкуп квартиры или жилого
помещения") is a DIRECT goods purchase: the object layer stays OFF
(object_applicable=False, OBJECT_* = N/A) and Layer 1 must produce no
embedded-product candidates.  The rule is boundary-safe, so construction /
repair / design of housing and equipment purchases keep OBJECT mode.
"""
from __future__ import annotations

from src.services import object_classification as OC
from src.services import product_candidate_materializer as MAT
from src.services import product_ontology as PO

WORKS = "WORKS_WITH_EMBEDDED_PRODUCTS"

# Section 2 positives: acquisition of finished dwelling space.
ACQUISITION_TITLES = (
    "Приобретение квартиры",
    "Покупка квартиры",
    "Приобретение жилого помещения",
    "Выкуп жилого помещения",
    "Приобретение жилых помещений (квартир) в государственную собственность Санкт-Петербурга",
    "Покупка жилого помещения, общей площадью не менее 33 кв.м.",
    "Приобретение квартиры путем участия в долевом строительстве многоквартирного жилого дома",
    "Приобретение в собственность благоустроенных жилых помещений для переселения граждан из аварийного дома",
)

# Section 8 regression negatives: NOT an acquisition, must stay OBJECT.
NON_ACQUISITION_TITLES = (
    "Строительство многоквартирного жилого дома",
    "Капитальный ремонт МКД",
    "Ремонт жилого помещения",
    "Проектирование жилого дома",
    "Приобретение и монтаж оборудования",
    "Поставка светильников",
    "Строительство автодороги",
    "Приобретение приборов учета электроэнергии в многоквартирных домах",
    "Приобретение оборудования системы видеонаблюдения с монтажом в нежилых помещениях",
    "Приобретение нежилого помещения в собственность Калужской области",
    "Выполнение работ по организации системы учета электроэнергии с удаленным сбором данных (включая приобретение приборов учета)",
)


def test_acquisition_titles_are_detected() -> None:
    for title in ACQUISITION_TITLES:
        assert MAT.is_dwelling_acquisition(title) is True, title


def test_non_acquisition_titles_are_not_detected() -> None:
    for title in NON_ACQUISITION_TITLES:
        assert MAT.is_dwelling_acquisition(title) is False, title


def test_detector_is_aside_aware_and_boundary_safe() -> None:
    # verb inside a parenthetical aside must not fire
    assert MAT.is_dwelling_acquisition(
        "Организация системы учета (включая приобретение приборов учета) в многоквартирных домах"
    ) is False
    # "многоквартирных" is not "квартира"; "нежилого помещения" is not dwelling
    assert MAT.is_dwelling_acquisition("Приобретение оборудования для многоквартирного дома") is False
    assert MAT.is_dwelling_acquisition("Приобретение нежилого помещения") is False
    # the dwelling noun must follow the verb in a short window
    assert MAT.is_dwelling_acquisition("Квартиры. " + "приобретение " + "x " * 200) is False


def test_detector_handles_missing_input() -> None:
    assert MAT.is_dwelling_acquisition(None) is False
    assert MAT.is_dwelling_acquisition("") is False
    assert MAT.is_dwelling_acquisition(12345) is False


def test_mode_gate_overrides_works_scope_for_acquisition() -> None:
    for title in ACQUISITION_TITLES:
        assert MAT.resolve_procurement_mode(WORKS, title=title) == PO.PROCUREMENT_MODE_DIRECT
    # provenance makes the override auditable
    mode, source = MAT.resolve_procurement_mode_with_source(WORKS, title="Приобретение квартиры")
    assert (mode, source) == (PO.PROCUREMENT_MODE_DIRECT, MAT.MODE_SOURCE_ACQUISITION)
    assert MAT.ACQUISITION_ARE_DIRECT is True


def test_mode_gate_is_backwards_compatible_and_keeps_negatives() -> None:
    # no title -> pure scope lookup, exactly as before
    assert MAT.resolve_procurement_mode(WORKS) == PO.PROCUREMENT_MODE_OBJECT
    assert MAT.resolve_procurement_mode("DIRECT_GOODS") == PO.PROCUREMENT_MODE_DIRECT
    assert MAT.resolve_procurement_mode(None) is None
    for title in NON_ACQUISITION_TITLES:
        assert MAT.resolve_procurement_mode(WORKS, title=title) == PO.PROCUREMENT_MODE_OBJECT, title
    # an acquisition is DIRECT whatever the scope authority said
    assert MAT.resolve_procurement_mode("PURE_SERVICE", title="Покупка квартиры") == PO.PROCUREMENT_MODE_DIRECT


def test_classification_is_direct_na_for_dwelling_purchase() -> None:
    for title in ACQUISITION_TITLES:
        row = OC.classify_from_title(WORKS, title)
        assert row.procurement_mode == "DIRECT", title
        assert row.status == OC.STATUS_DIRECT_NA, title
        assert row.object_applicable is False, title
        assert (row.object_sector, row.object_type, row.object_subtype) == ("N/A", "N/A", "N/A"), title
        assert row.classification_method == "MODE_DIRECT_ACQUISITION", title
        stored = row.as_row(1)
        assert OC.validate_classification(stored) == ()


def test_negatives_keep_their_object_classification() -> None:
    for title in NON_ACQUISITION_TITLES:
        row = OC.classify_from_title(WORKS, title)
        assert row.procurement_mode == "OBJECT", title
        assert row.status != OC.STATUS_DIRECT_NA, title
        assert row.object_type != "N/A", title
    # explicit section-8 expectations
    assert OC.classify_from_title(WORKS, "Строительство многоквартирного жилого дома").object_type == "APARTMENT_BUILDING"
    assert OC.classify_from_title(WORKS, "Капитальный ремонт МКД").object_type == "APARTMENT_BUILDING"
    assert OC.classify_from_title(WORKS, "Ремонт жилого помещения").object_type == "RESIDENTIAL_UNIT"
    assert OC.classify_from_title(WORKS, "Проектирование жилого дома").object_type == "APARTMENT_BUILDING"


def test_no_candidates_for_dwelling_purchase() -> None:
    signal = MAT.ObjectSignal(1, "DETERMINISTIC_HIGH_CONFIDENCE", "RESIDENTIAL", "APARTMENT_BUILDING")
    # the wrong (pre-remediation) object must not produce candidates once the gate is DIRECT
    assert MAT.build_candidates(PO.PROCUREMENT_MODE_DIRECT, signal) == []
    # end-to-end: title-aware mode -> DIRECT -> no candidates
    mode = MAT.resolve_procurement_mode(WORKS, title="Приобретение квартиры")
    assert MAT.build_candidates(mode, signal) == []


def test_stats_expose_the_acquisition_contract() -> None:
    stats = MAT.materializer_stats()
    assert stats["acquisition_are_direct"] is True
    assert stats["mode_source_acquisition"] == MAT.MODE_SOURCE_ACQUISITION
    assert stats["dwelling_acquisition_window"] == MAT.DWELLING_ACQUISITION_WINDOW


# --- DWELLING_ACQUISITION_BY_SUBJECT (OKPD + auction subject) ---------------
# Second, narrower path: the SUBJECT of the auction is finished dwelling space,
# so no acquisition verb is needed (e.g. the 4 verified "Квартира в
# многоквартирном жилом доме ..." cases).
OKPD_DWELLING_GOODS = "41.20.10.110"
PROGRAM_TITLE = (
    "Квартира в многоквартирном жилом доме, расположенном в г. Барыш муниципального "
    "образования «Барышский район» Ульяновской области в рамках реализации муниципальной "
    "программы «Развитие строительства и повышения уровня доступности жилых помещений и "
    "качества жилищного обеспечения населения», из многоквартирных домов, признанных с "
    "1 января 2017 года аварийными и подлежащими сносу или реконструкции, в 2025 и 2027 годах»»"
)
SUBJECT_ACQUISITION_CASES = (
    (PROGRAM_TITLE, OKPD_DWELLING_GOODS),
    (PROGRAM_TITLE, "41.20.10.120"),
    # coarse OKPD ancestor (41.2 covers construction works too) + programme context
    (PROGRAM_TITLE, "41.2"),
    (PROGRAM_TITLE, "41.20"),
    ("Приобретение жилого помещения, общей площадью не менее 33 кв.м.", OKPD_DWELLING_GOODS),
)
SUBJECT_NON_ACQUISITION_CASES = (
    (PROGRAM_TITLE, None),
    (PROGRAM_TITLE, ""),
    (PROGRAM_TITLE, "41.20.30.100"),  # not a finished-dwelling goods class
    (PROGRAM_TITLE, "41.21.1"),  # non-residential ancestor: never coarse-accepted
    ("Квартира в многоквартирном жилом доме в г. Пенза", "41.2"),  # coarse needs programme context
    ("Выполнение работ по капитальному ремонту жилого помещения", OKPD_DWELLING_GOODS),
    ("Капитальный ремонт квартиры по адресу г. Лобня", OKPD_DWELLING_GOODS),
    ("Строительство жилого дома, предоставляемого гражданам", OKPD_DWELLING_GOODS),
    ("Реконструкция жилого помещения", OKPD_DWELLING_GOODS),
    ("Проектирование жилого дома", OKPD_DWELLING_GOODS),
    ("Благоустройство территории многоквартирного дома", OKPD_DWELLING_GOODS),
    ("Устройство настила в квартире", OKPD_DWELLING_GOODS),
    ("Монтаж оборудования в жилом помещении", OKPD_DWELLING_GOODS),
)


SUBJECT_WORKS_TITLES = (
    "Выполнение работ по капитальному ремонту жилого помещения",
    "Капитальный ремонт квартиры по адресу г. Лобня",
    "Строительство жилого дома, предоставляемого гражданам",
    "Реконструкция жилого помещения",
    "Проектирование жилого дома",
    "Благоустройство территории многоквартирного дома",
    "Устройство настила в квартире",
    "Монтаж оборудования в жилом помещении",
)


def test_subject_rule_detects_dwelling_as_auction_subject() -> None:
    for title, okpd in SUBJECT_ACQUISITION_CASES:
        assert MAT.is_dwelling_acquisition_by_subject(title, okpd) is True, (title[:60], okpd)


def test_subject_rule_rejects_works_and_non_goods_okpd() -> None:
    for title, okpd in SUBJECT_NON_ACQUISITION_CASES:
        assert MAT.is_dwelling_acquisition_by_subject(title, okpd) is False, (title[:60], okpd)


def test_subject_rule_needs_both_okpd_and_subject() -> None:
    assert MAT.is_dwelling_acquisition_by_subject(None, OKPD_DWELLING_GOODS) is False
    assert MAT.is_dwelling_acquisition_by_subject("", OKPD_DWELLING_GOODS) is False
    assert MAT.is_dwelling_acquisition_by_subject("Ремонт автомобильной дороги", OKPD_DWELLING_GOODS) is False
    # works markers AFTER the subject are programme boilerplate, not the subject
    assert MAT.is_dwelling_acquisition_by_subject(PROGRAM_TITLE, OKPD_DWELLING_GOODS) is True


def test_subject_rule_mode_source_and_direct_gate() -> None:
    mode, source = MAT.resolve_procurement_mode_with_source(
        WORKS, title=PROGRAM_TITLE, okpd_code="41.2"
    )
    assert (mode, source) == (PO.PROCUREMENT_MODE_DIRECT, MAT.MODE_SOURCE_SUBJECT_ACQUISITION)
    assert MAT.resolve_procurement_mode(WORKS, title=PROGRAM_TITLE, okpd_code="41.2") == PO.PROCUREMENT_MODE_DIRECT
    # without okpd the subject rule cannot fire, and the verb rule does not apply
    assert MAT.resolve_procurement_mode(WORKS, title=PROGRAM_TITLE) == PO.PROCUREMENT_MODE_OBJECT
    # a works subject stays OBJECT even with a dwelling-goods OKPD
    for title in SUBJECT_WORKS_TITLES:
        assert MAT.resolve_procurement_mode(WORKS, title=title, okpd_code=OKPD_DWELLING_GOODS) == PO.PROCUREMENT_MODE_OBJECT, title


def test_subject_rule_classifies_direct_na_and_yields_no_candidates() -> None:
    row = OC.classify_from_title(WORKS, PROGRAM_TITLE, okpd_code="41.2")
    assert row.procurement_mode == "DIRECT"
    assert row.status == OC.STATUS_DIRECT_NA
    assert row.object_applicable is False
    assert (row.object_sector, row.object_type, row.object_subtype) == ("N/A", "N/A", "N/A")
    assert row.classification_method == "MODE_DIRECT_SUBJECT_ACQUISITION"
    assert OC.validate_classification(row.as_row(1)) == ()
    signal = MAT.ObjectSignal(1, "DETERMINISTIC_HIGH_CONFIDENCE", "RESIDENTIAL", "APARTMENT_BUILDING")
    assert MAT.build_candidates(row.procurement_mode, signal) == []


def test_stats_expose_the_subject_contract() -> None:
    stats = MAT.materializer_stats()
    assert stats["mode_source_subject_acquisition"] == MAT.MODE_SOURCE_SUBJECT_ACQUISITION
    assert list(stats["dwelling_goods_okpd_prefixes"]) == ["41.20.10"]
    assert list(stats["dwelling_goods_okpd_coarse"]) == ["41.2", "41.20"]
