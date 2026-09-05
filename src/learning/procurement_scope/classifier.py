from enum import Enum
from datetime import datetime
from typing import Dict, Any, List

class ProcurementScopeType(Enum):
    DIRECT_GOODS = "DIRECT_GOODS"
    WORKS_WITH_EMBEDDED_PRODUCTS = "WORKS_WITH_EMBEDDED_PRODUCTS"
    DESIGN_PROJECT = "DESIGN_PROJECT"
    EQUIPMENT_AND_INSTALLATION = "EQUIPMENT_AND_INSTALLATION"
    SERVICE_WITH_CONSUMABLES = "SERVICE_WITH_CONSUMABLES"
    PURE_SERVICE = "PURE_SERVICE"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"

class ProductRelation(Enum):
    PRIMARY_SUBJECT = "PRIMARY_SUBJECT"
    EMBEDDED_IN_WORKS = "EMBEDDED_IN_WORKS"
    SPECIFIED_IN_PROJECT = "SPECIFIED_IN_PROJECT"
    EQUIPMENT_WITH_INSTALLATION = "EQUIPMENT_WITH_INSTALLATION"
    CONSUMABLE_FOR_SERVICE = "CONSUMABLE_FOR_SERVICE"
    INCIDENTAL = "INCIDENTAL"
    UNKNOWN = "UNKNOWN"

class ProcurementScopeClassifierV1:
    def __init__(self):
        self.version = "1.0"
        self.model = "hybrid_rules_v1"
        
        # High confidence goods OKPD prefixes (20, 22, 23, 24, 25, 26, 27, 28)
        self.goods_okpd = ('20', '21', '22', '23', '24', '25', '26', '27', '28', '29', '30', '31', '32')
        # High confidence works
        self.works_okpd = ('41', '42', '43')
        # High confidence design
        self.design_okpd = ('71', '71.1', '71.11', '71.12')

    def classify(self, title: str, okpd_codes: List[str]) -> dict:
        title = str(title).lower()
        codes = [str(c) for c in okpd_codes] if okpd_codes else []
        
        # 1. High confidence explicit Title signals + Works
        is_construction = any(w in title for w in ['строительств', 'реконструкци', 'капитальный ремонт', 'текущий ремонт', 'устройство', 'монтаж', 'выполнение работ'])
        is_design = any(w in title for w in ['проектн', 'проектировани', 'пир', 'изыскания', 'рабочая документация'])
        is_supply = any(w in title for w in ['поставка', 'приобретение', 'закупка товара', 'поставка оборудования'])
        is_service = any(w in title for w in ['оказание услуг', 'обслуживание', 'техническое обслуживание', 'уборка', 'диагностика'])
        
        has_installation = 'монтаж' in title and ('поставка' in title or 'оборудовани' in title)
        has_consumables = is_service and any(w in title for w in ['материал', 'расходн'])

        if has_installation:
            return self._out(ProcurementScopeType.EQUIPMENT_AND_INSTALLATION, 0.95, "RULE_HIGH_CONFIDENCE", "Title contains supply and installation explicitly")
            
        if is_design:
            return self._out(ProcurementScopeType.DESIGN_PROJECT, 0.95, "RULE_HIGH_CONFIDENCE", "Title explicitly indicates design/project")
            
        if is_construction:
            return self._out(ProcurementScopeType.WORKS_WITH_EMBEDDED_PRODUCTS, 0.95, "RULE_HIGH_CONFIDENCE", "Title explicitly indicates construction/repair works")
            
        if has_consumables:
            return self._out(ProcurementScopeType.SERVICE_WITH_CONSUMABLES, 0.90, "RULE_HIGH_CONFIDENCE", "Title implies service with materials")
            
        if is_service and not is_supply:
            return self._out(ProcurementScopeType.PURE_SERVICE, 0.90, "RULE_HIGH_CONFIDENCE", "Title explicitly indicates service only")
            
        if is_supply and not is_construction and not is_design:
            return self._out(ProcurementScopeType.DIRECT_GOODS, 0.95, "RULE_HIGH_CONFIDENCE", "Title explicitly indicates direct goods supply")

        # 2. OKPD fallbacks
        if any(c.startswith(self.works_okpd) for c in codes):
            return self._out(ProcurementScopeType.WORKS_WITH_EMBEDDED_PRODUCTS, 0.85, "RULE_HIGH_CONFIDENCE", "OKPD strongly implies works")
            
        if any(c.startswith(self.design_okpd) for c in codes):
            return self._out(ProcurementScopeType.DESIGN_PROJECT, 0.85, "RULE_HIGH_CONFIDENCE", "OKPD strongly implies design")
            
        if any(c.startswith(self.goods_okpd) for c in codes):
            return self._out(ProcurementScopeType.DIRECT_GOODS, 0.85, "RULE_HIGH_CONFIDENCE", "OKPD strongly implies goods")
            
        return self._out(ProcurementScopeType.UNKNOWN, 0.0, "RULE_HIGH_CONFIDENCE", "Ambiguous evidence")

    def _out(self, scope_type: ProcurementScopeType, conf: float, source: str, reason: str):
        return {
            'procurement_scope_type': scope_type.value,
            'procurement_scope_confidence': conf,
            'procurement_scope_source': source,
            'procurement_scope_reason': reason,
            'procurement_scope_model': self.model,
            'procurement_scope_version': self.version,
            'procurement_scope_scored_at': datetime.now().isoformat()
        }

def derive_product_relation(scope_type_val: str) -> ProductRelation:
    mapping = {
        ProcurementScopeType.DIRECT_GOODS.value: ProductRelation.PRIMARY_SUBJECT,
        ProcurementScopeType.WORKS_WITH_EMBEDDED_PRODUCTS.value: ProductRelation.EMBEDDED_IN_WORKS,
        ProcurementScopeType.DESIGN_PROJECT.value: ProductRelation.SPECIFIED_IN_PROJECT,
        ProcurementScopeType.EQUIPMENT_AND_INSTALLATION.value: ProductRelation.EQUIPMENT_WITH_INSTALLATION,
        ProcurementScopeType.SERVICE_WITH_CONSUMABLES.value: ProductRelation.CONSUMABLE_FOR_SERVICE,
        ProcurementScopeType.PURE_SERVICE.value: ProductRelation.INCIDENTAL,
        ProcurementScopeType.MIXED.value: ProductRelation.UNKNOWN,
        ProcurementScopeType.UNKNOWN.value: ProductRelation.UNKNOWN
    }
    return mapping.get(scope_type_val, ProductRelation.UNKNOWN)
