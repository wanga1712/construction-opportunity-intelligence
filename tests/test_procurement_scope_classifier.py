from src.learning.procurement_scope.classifier import ProcurementScopeClassifierV1, ProcurementScopeType, derive_product_relation, ProductRelation
from src.services.research_queue_priority import get_effective_service_band, BAND_GOLD, BAND_BRONZE, BAND_WOOD

def run_tests():
    clf = ProcurementScopeClassifierV1()
    tests = [
        ("Поставка расходных материалов для цветного принтера", [], ProcurementScopeType.DIRECT_GOODS),
        ("Капитальный ремонт укрепительных сооружений автомобильной дороги", [], ProcurementScopeType.WORKS_WITH_EMBEDDED_PRODUCTS),
        ("Устройство слоев износа автомобильной дороги", [], ProcurementScopeType.WORKS_WITH_EMBEDDED_PRODUCTS),
        ("Разработка проектной документации", [], ProcurementScopeType.DESIGN_PROJECT),
        ("Поставка оборудования с монтажом и пусконаладкой", [], ProcurementScopeType.EQUIPMENT_AND_INSTALLATION),
        ("Оказание услуг по уборке помещений", [], ProcurementScopeType.PURE_SERVICE),
    ]
    
    passed = 0
    for title, okpd, expected in tests:
        res = clf.classify(title, okpd)
        if res['procurement_scope_type'] == expected.value:
            passed += 1
        else:
            print(f"FAIL: {title} expected {expected.value} got {res['procurement_scope_type']}")
            
    # test product relations
    assert derive_product_relation(ProcurementScopeType.DIRECT_GOODS.value) == ProductRelation.PRIMARY_SUBJECT
    assert derive_product_relation(ProcurementScopeType.WORKS_WITH_EMBEDDED_PRODUCTS.value) == ProductRelation.EMBEDDED_IN_WORKS
    assert derive_product_relation(ProcurementScopeType.DESIGN_PROJECT.value) == ProductRelation.SPECIFIED_IN_PROJECT
    assert derive_product_relation(ProcurementScopeType.SERVICE_WITH_CONSUMABLES.value) == ProductRelation.CONSUMABLE_FOR_SERVICE
    assert derive_product_relation(ProcurementScopeType.MIXED.value) == ProductRelation.UNKNOWN

    # test DIRECT_GOODS_PRIORITY_OVERRIDE
    # 1. DIRECT_GOODS >= 50_000 -> GOLD
    row1 = {"procurement_scope_type": "DIRECT_GOODS", "normalized_nmck_rub": 60000, "research_prior_band": BAND_BRONZE}
    assert get_effective_service_band(row1) == BAND_GOLD

    # 2. DIRECT_GOODS < 50_000 -> normal band (BRONZE)
    row2 = {"procurement_scope_type": "DIRECT_GOODS", "normalized_nmck_rub": 40000, "research_prior_band": BAND_BRONZE}
    assert get_effective_service_band(row2) == BAND_BRONZE

    # 3. WORKS >= 50_000 -> normal band (WOOD)
    row3 = {"procurement_scope_type": "WORKS_WITH_EMBEDDED_PRODUCTS", "normalized_nmck_rub": 1000000, "research_prior_band": BAND_WOOD}
    assert get_effective_service_band(row3) == BAND_WOOD

    print(f"Passed {passed}/{len(tests)} targeted tests and priority override checks")

if __name__ == '__main__':
    run_tests()
