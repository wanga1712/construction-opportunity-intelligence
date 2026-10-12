"""Hard-veto rules for obviously out-of-category titles."""
from src.services.commercial_routing_v3.category_hard_veto import (
    REASON_ROAD_WORKS_OUT_OF_CATEGORY,
    hard_veto_reason,
)

ROAD_LAYER = "Устройство слоёв износа на автомобильной дороге А-149, Краснодарский край"
LIGHTING_MAINT = ("Выполнение работ по круглогодичному содержанию линий наружного освещения "
                  "на автомобильных дорогах общего пользования Московской области (Лот 2.4)")


def test_road_layers_vetoed_for_lighting():
    assert hard_veto_reason("lighting", ROAD_LAYER) == REASON_ROAD_WORKS_OUT_OF_CATEGORY


def test_lighting_maintenance_not_vetoed_for_lighting():
    # Explicit lighting wording must survive even with "содержание ... дорог".
    assert hard_veto_reason("lighting", LIGHTING_MAINT) is None


def test_lighting_maintenance_vetoed_for_curbstone():
    assert hard_veto_reason("curbstone", LIGHTING_MAINT) == REASON_ROAD_WORKS_OUT_OF_CATEGORY


def test_unrelated_title_not_vetoed():
    assert hard_veto_reason("lighting", "Поставка светодиодных светильников") is None
    assert hard_veto_reason("lighting", "Поставка товаров") is None


TRAM_REPAIR = ("Выполнение работ по ремонту трамвайных путей Санкт-Петербурга "
               "в рамках реализации адресной программы, Выборгский район")


def test_tram_repair_vetoed_for_curbstone():
    assert hard_veto_reason("curbstone", TRAM_REPAIR) == REASON_ROAD_WORKS_OUT_OF_CATEGORY


def test_explicit_curbstone_not_vetoed():
    assert hard_veto_reason("curbstone", "Поставка бордюрного камня БР 100.30.15") is None


BRIDGE_BUILD = ("Выполнение работ по строительству автомобильной дороги «Переход ул. Строителей "
                "от площади Гайдара до ул. Стахановская». Участок от шоссе Космонавтов до ул. Крисанова")


def test_bridge_build_curbstone_allowed():
    # Bridges/embankments do use curbstone (operator feedback) -> never veto by "bridge".
    assert hard_veto_reason("curbstone", BRIDGE_BUILD) is None


def test_bridge_build_lighting_not_vetoed():
    # A road/bridge build may well contain lighting, composite, barriers.
    assert hard_veto_reason("lighting", BRIDGE_BUILD) is None
    assert hard_veto_reason("composite_structures", BRIDGE_BUILD) is None


AIRPORT_REPAIR = "Капитальный ремонт аэродрома Барнаул (Михайловка)"


def test_airport_repair_curbstone_vetoed_but_lighting_ok():
    assert hard_veto_reason("curbstone", AIRPORT_REPAIR) == REASON_ROAD_WORKS_OUT_OF_CATEGORY
    assert hard_veto_reason("lighting", AIRPORT_REPAIR) is None


IMPROVEMENT = ("Выполнение работ по капитальному ремонту по благоустройству территории "
               "в ГКУ СО МО Семейный центр помощи семье и детям «Семья и дом»")


def test_urban_improvement_waterproofing_vetoed_lighting_and_curbstone_ok():
    assert hard_veto_reason("waterproofing", IMPROVEMENT) == REASON_ROAD_WORKS_OUT_OF_CATEGORY
    assert hard_veto_reason("lighting", IMPROVEMENT) is None
    assert hard_veto_reason("curbstone", IMPROVEMENT) is None


ROAD_REPAIR_WITH_BRIDGE_LANDMARK = (
    "Ремонт автомобильной дороги от Боталовского моста до м/р Усть-Нытва (км 004+150 - км 005+059)")


def test_road_repair_waterproofing_vetoed():
    assert hard_veto_reason("waterproofing", ROAD_REPAIR_WITH_BRIDGE_LANDMARK) == REASON_ROAD_WORKS_OUT_OF_CATEGORY
    # Repairing a bridge itself may involve waterproofing -> no veto just for "мост".
    assert hard_veto_reason("waterproofing", "Ремонт моста через реку, гидроизоляция пролётного строения") is None


SERVICE_COMM = ("Текущий ремонт и техническое обслуживание инженерных коммуникаций, "
                "обслуживание бассейнов и ремонт конструктивных элементов здания Городских бань")


def test_service_maintenance_global_veto_any_category():
    from src.services.commercial_routing_v3.category_hard_veto import (
        REASON_SERVICE_MAINTENANCE_OUT_OF_SCOPE,
    )
    for cat in ("waterproofing", "lighting", "flooring", None):
        assert hard_veto_reason(cat, SERVICE_COMM) == REASON_SERVICE_MAINTENANCE_OUT_OF_SCOPE


def test_gravel_road_composite_vetoed():
    title = "Право заключения муниципального контракта на строительство щебеночной дороги по ул. Южная в н.п. Хлыстово"
    assert hard_veto_reason("composite_structures", title) == REASON_ROAD_WORKS_OUT_OF_CATEGORY
    # Bridge build stays allowed for composites (railings/bearings).
    assert hard_veto_reason("composite_structures", BRIDGE_BUILD) is None


def test_road_safety_items_composite_vetoed():
    title = ("Выполнение работ по устройству искусственной дорожной неровности "
             "(лежачего полицейского), нанесение разметки, устройство дорожных знаков в г. Суздаль")
    assert hard_veto_reason("composite_structures", title) == REASON_ROAD_WORKS_OUT_OF_CATEGORY


def test_podd_global_veto_and_stops_not_lighting_and_pavement_not_composite():
    podd = ("Выполнение комплекса работ по обследованию и разработке проектов организации "
            "дорожного движения (ПОДД) на дворовых территориях городского округа Домодедово")
    assert hard_veto_reason("drainage_water_management", podd) == "SERVICE_MAINTENANCE_OUT_OF_SCOPE"

    stops = "Выполнение работ по обустройству остановочных павильонов и дорожных ограждений"
    assert hard_veto_reason("lighting", stops) == REASON_ROAD_WORKS_OUT_OF_CATEGORY

    pavement = ("Выполнение работ по устранению повреждений дорожного покрытия "
                "на автомобильных дорогах общего пользования")
    assert hard_veto_reason("composite_structures", pavement) == REASON_ROAD_WORKS_OUT_OF_CATEGORY


def test_gravel_fill_vetoed_for_curbstone_lighting_drainage():
    title = "Выполнение работ по отсыпке щебнем участков дороги на ул. Шипово"
    for cat in ("curbstone", "lighting", "drainage_water_management", "composite_structures"):
        assert hard_veto_reason(cat, title) == REASON_ROAD_WORKS_OUT_OF_CATEGORY, cat


def test_road_marking_curbstone_vetoed():
    title = ("Выполнение работ по устройству разметки, установке, ремонту и содержанию "
             "элементов обустройства автомобильных дорог общего пользования местного значения "
             "городской округ город-курорт Сочи")
    assert hard_veto_reason("curbstone", title) == REASON_ROAD_WORKS_OUT_OF_CATEGORY
