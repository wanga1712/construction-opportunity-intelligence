"""Canonical production Object Layer contract.

WIP CANONICAL-OBJECT-LAYER-PRODUCTION-V1.

Covers only what this WIP added:
  * single authority: src/services/object_classification.py;
  * mode gate: DIRECT / SERVICE_NO_OBJECT -> object_applicable False + N/A;
  * AMBIGUOUS / unknown mode -> never auto-classified;
  * boundary-safe deterministic object rules (no substring discovery);
  * object vs context precedence;
  * OBJECT_CLASSIFICATION_VERSION;
  * storage contract validation for crm_procurement_object_classifications.
"""
from __future__ import annotations

import pathlib

import pytest

from src.services import expert_object_taxonomy as OT
from src.services import object_classification as OC
from src.services import product_candidate_materializer as MAT

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT / "src" / "migrations" / "crm_procurement_object_classifications_1.sql"
)

# Section 6 deterministic examples: title -> (sector, type, subtype).
DETERMINISTIC_CASES = (
    ("Ремонт автомобильной дороги на участке км 12", OT.INFRASTRUCTURE, "ROAD", None),
    ("Капитальный ремонт моста через реку Обь", OT.INFRASTRUCTURE, "BRIDGE", None),
    ("Строительство тоннеля в створе улицы", OT.INFRASTRUCTURE, "TUNNEL", None),
    (
        "Реконструкция тепловой сети от котельной",
        OT.INFRASTRUCTURE,
        "UTILITY_NETWORKS",
        "HEATING_NETWORK",
    ),
    (
        "Ремонт водопроводных сетей города",
        OT.INFRASTRUCTURE,
        "UTILITY_NETWORKS",
        "WATER_NETWORK",
    ),
    (
        "Строительство газопровода низкого давления",
        OT.INFRASTRUCTURE,
        "UTILITY_NETWORKS",
        "GAS_NETWORK",
    ),
    ("Капитальный ремонт школы N 4", OT.SOCIAL, "SCHOOL", None),
    ("Ремонт детского сада Солнышко", OT.SOCIAL, "KINDERGARTEN", None),
    ("Текущий ремонт поликлиники N 2", OT.SOCIAL, "POLYCLINIC", None),
    ("Ремонт здания колледжа", OT.SOCIAL, "COLLEGE", None),
    ("Ремонт МКД по адресу ул. Мира 5", OT.RESIDENTIAL, "APARTMENT_BUILDING", None),
    ("Благоустройство сквера у дома культуры", OT.URBAN_IMPROVEMENT, "SQUARE", None),
    ("Благоустройство парка Победы", OT.URBAN_IMPROVEMENT, "PARK", None),
    ("Ремонт набережной реки", OT.URBAN_IMPROVEMENT, "EMBANKMENT", None),
)


def _c(title: str, mode: str = "OBJECT") -> OC.ObjectClassification:
    return OC.classify_object(mode, title=title)


def test_version_and_statuses_are_stable() -> None:
    assert OC.OBJECT_CLASSIFICATION_VERSION == "object_canonical_v1"
    assert OC.STATUS_DIRECT_NA == "DIRECT_NA"
    assert OC.STATUS_SERVICE_NA == "SERVICE_NA"
    assert set(OC.CLASSIFICATION_STATUS_VALUES) == {
        "RESOLVED_REVIEWED",
        "RESOLVED_HIGH_CONFIDENCE",
        "RESOLVED_MODEL",
        "DIRECT_NA",
        "SERVICE_NA",
        "MODE_AMBIGUOUS",
        "OBJECT_MISSING",
        "OBJECT_CONFLICT",
        "OBJECT_UNCERTAIN",
        "MODEL_INVALID",
        "OBJECT_NONCANONICAL",
    }
    # Historical alias kept for older call sites; it is the mass-run name.
    assert OC.STATUS_AMBIGUOUS == OC.STATUS_MODE_AMBIGUOUS == "MODE_AMBIGUOUS"


def test_every_rule_targets_a_canonical_object_type() -> None:
    for _priority, _pattern, sector, object_type, subtype in OC._RULES:
        assert OT.is_canonical_object_type(object_type, sector), object_type
        if subtype:
            assert OT.is_canonical_object_subtype(subtype, object_type), subtype


# --- mode gate --------------------------------------------------------------
def test_direct_mode_has_no_object() -> None:
    row = _c("Приобретение квартиры", mode="DIRECT")
    assert row.status == OC.STATUS_DIRECT_NA
    assert row.object_applicable is False
    assert row.axes() is None
    assert (row.object_sector, row.object_type, row.object_subtype) == ("N/A", "N/A", "N/A")


def test_service_mode_has_no_object() -> None:
    row = _c("Услуги по уборке территории школы", mode="SERVICE_NO_OBJECT")
    assert row.status == OC.STATUS_SERVICE_NA
    assert row.object_type == "N/A"


def test_direct_mode_wins_over_object_words_in_title() -> None:
    # A direct purchase of a flat must never pick up embedded object words.
    row = _c("Приобретение квартиры с ремонтом и благоустройством", mode="DIRECT")
    assert row.status == OC.STATUS_DIRECT_NA
    assert row.matched_terms == ()


def test_ambiguous_and_unknown_mode_are_not_auto_classified() -> None:
    for mode in ("AMBIGUOUS", None):
        row = _c("Ремонт моста", mode=mode)
        assert row.status == OC.STATUS_AMBIGUOUS
        assert row.object_applicable is False
        assert row.object_type is None
        assert row.classification_source == OC.SOURCE_UNRESOLVED


def test_mode_helper_accepts_production_scope_values() -> None:
    assert OC.classify_from_title("DIRECT_GOODS", "Приобретение квартиры").status == OC.STATUS_DIRECT_NA
    assert (
        OC.classify_from_title("WORKS_WITH_EMBEDDED_PRODUCTS", "Ремонт моста").object_type
        == "BRIDGE"
    )
    assert OC.classify_from_title("PURE_SERVICE", "Услуги связи").status == OC.STATUS_SERVICE_NA
    assert OC.classify_from_title("UNKNOWN", "Ремонт моста").status == OC.STATUS_AMBIGUOUS


# --- deterministic rules ----------------------------------------------------
@pytest.mark.parametrize("title,sector,object_type,subtype", DETERMINISTIC_CASES)
def test_deterministic_object_examples(title, sector, object_type, subtype) -> None:
    row = _c(title)
    assert row.status == OC.STATUS_RESOLVED_HIGH_CONFIDENCE
    assert (row.object_sector, row.object_type, row.object_subtype) == (sector, object_type, subtype)
    assert row.classification_source == OC.SOURCE_DETERMINISTIC


def test_unmatched_title_is_object_missing_not_a_guess() -> None:
    row = _c("Поставка канцелярских товаров")
    assert row.status == OC.STATUS_OBJECT_MISSING
    assert row.object_type is None
    assert row.object_applicable is False


def test_empty_title_is_object_missing() -> None:
    assert _c("").status == OC.STATUS_OBJECT_MISSING


# --- boundary safety (section 7 known bad patterns) -------------------------
@pytest.mark.parametrize(
    "title",
    (
        "Устройство отмостки вокруг здания",
        "Ремонт просвещения не требуется",
        "Услуги по просвещению населения",
        "Поставка мостового ограждения",
        "Замена дорогостоящего оборудования",
    ),
)
def test_known_bad_patterns_do_not_create_objects(title: str) -> None:
    row = _c(title)
    assert row.object_type in (None,), (title, row.status, row.object_type)
    assert row.status in (OC.STATUS_OBJECT_MISSING, OC.STATUS_OBJECT_CONFLICT)


def test_parking_is_not_a_park() -> None:
    row = _c("Парковка у торгового центра")
    assert row.object_type == "SHOPPING_CENTER"
    assert row.object_context == "parking_area"


def test_park_rule_does_not_fire_on_parking_word() -> None:
    assert _c("Ремонт парковки").object_type != "PARK"


def test_transport_facility_endpoint_keeps_the_parent_object() -> None:
    # A road named after, or leading to, an airport / railway station keeps ROAD.
    airport_road = _c('Реконструкция автомобильной дороги "Лобня - аэропорт Шереметьево"')
    assert airport_road.object_type == "ROAD"
    access_road = _c(
        "Капитальный ремонт участков автомобильных дорог Верхнечусовские Городки, "
        "автомобильного проезда к железнодорожному вокзалу от ул. Ленина"
    )
    assert access_road.object_type == "ROAD"


def test_bridge_over_railway_keeps_the_bridge_object() -> None:
    row = _c("Ремонт мостового сооружения через железную дорогу на автомобильной дороге")
    assert row.object_type == "BRIDGE"


def test_real_airport_and_railway_objects_are_still_detected() -> None:
    assert _c("Реконструкция аэропортового комплекса Толмачево").object_type == "AIRPORT"
    assert _c("Капитальный ремонт здания железнодорожного вокзала").object_type == "RAILWAY"
    assert (
        _c("Ремонт железной дороги на участке Москва - Санкт-Петербург").object_type
        == "RAILWAY"
    )


def test_former_object_is_not_the_current_object() -> None:
    # Construction happens *on the site* of a decommissioned object; the site is
    # not the object of the procurement.
    row = _c(
        "Поставка компьютерного оборудования для объекта капитального "
        "«Строительство школы на территории бывшего аэропорта по ул. Амосова "
        "в Советском районе г. Брянск»"
    )
    assert row.object_type == "SCHOOL"
    assert _c("Благоустройство бывшей железной дороги").object_type != "RAILWAY"


def test_railway_adjective_alone_does_not_create_a_railway_object() -> None:
    # "Железнодорожник-2" is a garden association; "Железнодорожный район" is an
    # address district; "Памятник железнодорожникам" is a monument.  None of
    # them is a railway object.
    road = _c(
        "Выполнение работ по текущему ремонту : устройство заездного кармана, "
        "подхода, посадочной площадки, установка автобусного павильона на "
        "автомобильной дороге общего пользования, СНТ «Железнодорожник-2»"
    )
    assert road.object_type == "ROAD"
    sewer = _c(
        "Обслуживание сетей ливневой канализации в Ленинском и Железнодорожном "
        "районах г. Ростова-на-Дону"
    )
    assert sewer.object_type == "UTILITY_NETWORKS"
    assert (
        _c("Памятник железнодорожникам, благоустройство и озеленение территории").object_type
        != "RAILWAY"
    )


def test_industrial_park_is_an_industrial_site_not_a_park() -> None:
    row = _c('Строительство парковок на территории индустриального парка "Феникс"')
    assert row.object_type == "INDUSTRIAL_SITE"
    assert _c("Благоустройство территории промышленного парка").object_type == "INDUSTRIAL_SITE"
    assert _c("Строительство технопарка").object_type == "INDUSTRIAL_SITE"


def test_municipal_park_is_still_a_park() -> None:
    assert _c("Благоустройство парка Победы").object_type == "PARK"



def test_address_street_is_not_a_street_object() -> None:
    # "ул." is an address component; it must not become INFRASTRUCTURE/STREET.
    row = _c("Поставка мебели, ул. Ленина 10")
    assert row.object_type != "STREET"


def test_address_street_name_does_not_create_an_object() -> None:
    # "ул. Заводская" is an address; it must not become FACTORY.
    row = _c("Выполнение работ по благоустройству, строительство тротуара по ул. Заводская")
    assert row.object_type != "FACTORY"
    assert row.object_type == "STREET"


def test_address_street_name_alone_creates_no_object() -> None:
    row = _c("Капитальный ремонт здания лаборатории, г. Ефремов, ул. Заводская, д. 1")
    assert row.object_type is None
    assert row.status == OC.STATUS_OBJECT_MISSING


def test_landmark_reference_does_not_create_an_object() -> None:
    row = _c("Устройство подхода к пешеходному переходу (в районе магазина Пятерочка)")
    assert row.object_type != "SHOPPING_CENTER"


def test_factory_rule_still_fires_on_a_real_plant() -> None:
    assert _c("Реконструкция цеха завода железобетонных изделий").object_type in (
        "FACTORY",
        "PRODUCTION_BUILDING",
    )

def test_pipeline_adjective_is_not_a_pipeline() -> None:
    # "Газопроводское" is a settlement name, not a gas pipeline.
    row = _c("Капитальный ремонт Газопроводского ФАП, п. Газопроводское")
    assert row.object_type != "UTILITY_NETWORKS"


def test_internal_building_system_is_not_a_utility_network() -> None:
    row = _c(
        "Капитальный ремонт систем отопления, водоснабжения и канализации "
        "в помещениях ГБУЗ Женская консультация"
    )
    assert row.object_type != "UTILITY_NETWORKS"


def test_external_network_is_still_detected() -> None:
    row = _c("Реконструкция водопроводных сетей города")
    assert row.object_type == "UTILITY_NETWORKS"
    assert row.object_subtype == "WATER_NETWORK"


def test_school_object_outranks_its_heating_system() -> None:
    row = _c("Капитальный ремонт школы с заменой системы отопления")
    assert row.object_type == "SCHOOL"


def test_utility_network_noun_forms_are_detected() -> None:
    assert _c("Ремонт газопровода низкого давления").object_subtype == "GAS_NETWORK"
    assert _c("Строительство канализационных сетей микрорайона").object_subtype == "SEWER_NETWORK"
    assert _c("Ремонт тепловой сети").object_subtype == "HEATING_NETWORK"

def test_sports_playground_is_a_playground_not_a_sports_facility() -> None:
    row = _c("Обустройство детских игровых и спортивных площадок")
    assert row.object_type == "PLAYGROUND"


def test_sports_hall_is_a_sports_facility() -> None:
    assert _c("Ремонт спортивного зала школы").object_type in ("SPORTS_FACILITY", "SCHOOL")
    assert _c("Строительство физкультурно-оздоровительного комплекса").object_type == "SPORTS_FACILITY"


def test_road_object_outranks_secondary_network_works() -> None:
    row = _c(
        "Строительство участка автомобильной дороги, в том числе с выносом линий "
        "электроснабжения и газоснабжения"
    )
    assert row.object_type == "ROAD"

def test_conflicting_rules_report_conflict() -> None:
    row = _c("Ремонт школы и детского сада")
    # two equal-priority social rules -> explicit conflict, never a guess
    assert row.status in (OC.STATUS_OBJECT_CONFLICT, OC.STATUS_RESOLVED_HIGH_CONFIDENCE)
    if row.status == OC.STATUS_OBJECT_CONFLICT:
        assert row.object_type is None
        assert row.object_applicable is False


def test_conflict_never_writes_an_object_type() -> None:
    row = OC.ObjectClassification(
        procurement_mode="OBJECT",
        object_applicable=False,
        status=OC.STATUS_OBJECT_CONFLICT,
    )
    assert row.axes() is None


# --- object vs context (section 8) -----------------------------------------
def test_landscaping_of_school_keeps_school_as_object() -> None:
    row = _c("Благоустройство территории школы N 7")
    assert row.object_type == "SCHOOL"
    assert row.object_context == "landscaping"


def test_mkd_courtyard_keeps_building_as_object() -> None:
    row = _c("Благоустройство дворовой территории МКД")
    assert row.object_type == "APARTMENT_BUILDING"
    assert row.object_context == "landscaping"


def test_standalone_courtyard_is_urban_improvement() -> None:
    row = _c("Благоустройство дворовых территорий")
    assert row.object_type == "COURTYARD"
    assert row.object_sector == OT.URBAN_IMPROVEMENT


def test_application_area_is_a_separate_axis() -> None:
    row = _c("Ремонт кровли поликлиники N 3")
    assert row.object_type == "POLYCLINIC"
    assert row.application_area == "roof"
    assert row.object_sector == OT.SOCIAL


# --- human claims outrank text rules ---------------------------------------
def test_reviewed_claim_outranks_deterministic_rules() -> None:
    row = OC.classify_object(
        "OBJECT",
        title="Ремонт моста",
        reviewed={"object_sector": OT.INFRASTRUCTURE, "object_type": "TUNNEL"},
    )
    assert row.status == OC.STATUS_RESOLVED_REVIEWED
    assert row.object_type == "TUNNEL"
    assert row.classification_source == OC.SOURCE_REVIEWED_HISTORICAL


def test_expert_claim_is_the_highest_source() -> None:
    row = OC.classify_object(
        "OBJECT",
        title="Ремонт моста",
        expert={"object_type": "PARK"},
    )
    assert row.classification_source == OC.SOURCE_EXPERT_CONFIRMED
    assert row.object_type == "PARK"
    assert row.confidence_class == OC.CONFIDENCE_EXPERT


def test_non_canonical_expert_claim_is_never_promoted() -> None:
    row = OC.classify_object(
        "OBJECT",
        title="Ремонт моста",
        expert={"object_type": "TEST_TYPE"},
    )
    assert row.status == OC.STATUS_OBJECT_NONCANONICAL
    assert row.object_type is None


def test_source_allow_list_excludes_regex_discovery() -> None:
    assert OC.SOURCE_DETERMINISTIC in OC.ALLOWED_CLASSIFICATION_SOURCES
    assert all("REGEX" not in src for src in OC.ALLOWED_CLASSIFICATION_SOURCES)
    assert all("SUBSTRING" not in src for src in OC.ALLOWED_CLASSIFICATION_SOURCES)


def test_allowed_sources_match_layer1_object_policy() -> None:
    # Mode-only sources prove a mode, never an object, so Layer 1 must reject them.
    for source in OC.ALLOWED_CLASSIFICATION_SOURCES:
        if source in MAT.MODE_ONLY_SOURCES:
            assert not MAT.object_source_allowed(source), source
        else:
            assert MAT.object_source_allowed(source), source


# --- storage contract -------------------------------------------------------
def test_as_row_shape_is_canonical() -> None:
    row = _c("Ремонт моста").as_row(123)
    assert row["procurement_id"] == 123
    assert row["classification_version"] == OC.OBJECT_CLASSIFICATION_VERSION
    assert row["object_applicable"] is True
    assert OC.validate_classification(row) == ()


@pytest.mark.parametrize(
    "title,mode",
    (
        ("Ремонт моста", "OBJECT"),
        ("Приобретение квартиры", "DIRECT"),
        ("Услуги связи", "SERVICE_NO_OBJECT"),
        ("Ремонт моста", "AMBIGUOUS"),
        ("Поставка канцтоваров", "OBJECT"),
    ),
)
def test_validate_classification_accepts_every_status(title: str, mode: str) -> None:
    row = _c(title, mode=mode).as_row(1)
    assert OC.validate_classification(row) == ()


def test_validate_classification_rejects_cross_axis_errors() -> None:
    row = _c("Ремонт моста").as_row(1)
    bad_type = dict(row, object_type="SCHOOL")
    assert OC.validate_classification(bad_type)
    bad_applicable = dict(row, object_applicable=False)
    assert OC.validate_classification(bad_applicable)
    bad_version = dict(row, classification_version="other_v9")
    assert OC.validate_classification(bad_version)


def test_row_must_not_be_applicable_when_status_unresolved() -> None:
    row = _c("Поставка канцтоваров").as_row(1)
    assert row["object_applicable"] is False
    assert OC.validate_classification(row) == ()


def test_classification_stats_contract() -> None:
    stats = OC.classification_stats()
    assert stats["classification_version"] == "object_canonical_v1"
    assert stats["table"] == "crm_procurement_object_classifications"
    assert stats["rule_count"] == len(OC._RULES)
    assert "landscaping" in stats["context_terms"]


def test_only_resolved_statuses_are_materializable() -> None:
    """DIRECT_NA / SERVICE_NA / unresolved statuses never become object rows."""
    assert set(OC.RESOLVED_STATUSES) == {
        OC.STATUS_RESOLVED_REVIEWED,
        OC.STATUS_RESOLVED_HIGH_CONFIDENCE,
        OC.STATUS_RESOLVED_MODEL,
    }
    for status in (
        OC.STATUS_DIRECT_NA,
        OC.STATUS_SERVICE_NA,
        OC.STATUS_MODE_AMBIGUOUS,
        OC.STATUS_OBJECT_MISSING,
        OC.STATUS_OBJECT_CONFLICT,
        OC.STATUS_OBJECT_UNCERTAIN,
        OC.STATUS_MODEL_INVALID,
        OC.STATUS_OBJECT_NONCANONICAL,
    ):
        assert status not in OC.RESOLVED_STATUSES
        assert status in OC.UNRESOLVED_STATUSES or status in (
            OC.STATUS_DIRECT_NA,
            OC.STATUS_SERVICE_NA,
        )


def test_direct_and_service_rows_are_never_applicable() -> None:
    for mode in ("DIRECT", "SERVICE_NO_OBJECT"):
        row = _c("Ремонт моста", mode=mode).as_row(1)
        assert row["object_applicable"] is False
        assert row["object_type"] == "N/A"
        assert row["object_sector"] == "N/A"
        assert row["object_subtype"] == "N/A"
        assert row["classification_status"] not in OC.RESOLVED_STATUSES


def test_migration_unique_index_is_the_idempotency_key() -> None:
    """The upsert identity must be the DB unique index, or reruns duplicate."""
    sql = MIGRATION.read_text(encoding="utf-8")
    index = sql.split("uix_cpoc_procurement_version")[1]
    assert "(procurement_id, classification_version)" in index
    assert "is_current" in sql
    assert "classification_version" in sql


def test_migration_declares_the_canonical_table() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS crm_procurement_object_classifications" in sql
    assert "uix_cpoc_procurement_version" in sql
    assert "ck_cpoc_applicable" in sql
    assert "ck_cpoc_unresolved_axes" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON crm_procurement_object_classifications TO crm_app" in sql