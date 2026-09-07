"""Fail-closed procurement scope classification before document research."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


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


_SUPPLY_RE = re.compile(r"поставк|приобретени|закупк\w*\s+товар", re.I)
_WORK_RE = re.compile(
    r"строительств|реконструкц|капитальн\w*\s+ремонт|текущ\w*\s+ремонт|"
    r"устройств\w+\s+(дорог|сет|полотн)|выполнени\w*\s+работ", re.I
)
_DESIGN_RE = re.compile(
    r"проектн\w*\s+документац|разработк\w*\s+проект|проектирован|"
    r"инженерн\w*\s+изыскани|рабоч\w*\s+документац", re.I
)
_SERVICE_RE = re.compile(
    r"оказани\w*\s+услуг|техническ\w*\s+обслужив|обслужив|уборк|диагностик", re.I
)
_INSTALL_RE = re.compile(r"монтаж|пусконалад|установк", re.I)
_CONSUMABLE_RE = re.compile(r"материал|расходн|комплектующ", re.I)
_PRODUCT_RE = re.compile(
    r"линолеум|ламп|светильник|компьютер|сервер|принтер|кабел|"
    r"оборудован|покрыти\w*\s+пола|плитк|материал", re.I
)
_PRODUCT_OKPD_PREFIXES = (
    "20.", "21.", "22.", "23.", "24.", "25.", "26.", "27.",
    "28.", "29.", "30.", "31.", "32.",
)


class ProcurementScopeClassifierV1:
    """Classify procurement scope from pre-research metadata only."""

    version = "1.1"
    model = "pre_research_rules_v1"

    def classify(self, title: str, okpd_codes: List[str]) -> dict:
        return self.classify_procurement({"title": title, "okpd_codes": okpd_codes})

    def classify_procurement(self, metadata: Dict[str, Any]) -> dict:
        title = self._title(metadata)
        okpd = [str(code).strip() for code in metadata.get("okpd_codes") or [] if code]
        text = " ".join(
            str(metadata.get(key) or "")
            for key in (
                "title",
                "auction_name",
                "subject",
                "purchase_object",
                "lot_item_names",
            )
        ).strip()
        lower = text.lower()
        has_supply = bool(_SUPPLY_RE.search(text))
        has_work = bool(_WORK_RE.search(text))
        has_design = bool(_DESIGN_RE.search(text))
        has_service = bool(_SERVICE_RE.search(text))
        has_install = bool(_INSTALL_RE.search(text))
        has_consumable = bool(_CONSUMABLE_RE.search(text))
        has_product = bool(_PRODUCT_RE.search(text))
        product_okpd = any(code.startswith(_PRODUCT_OKPD_PREFIXES) for code in okpd)

        if has_design and has_work and has_supply:
            return self._out(ProcurementScopeType.MIXED, 0.80, "TITLE_PRE_RESEARCH", "design+works+supply")
        if has_supply and has_install and ("оборудован" in lower or product_okpd):
            return self._out(ProcurementScopeType.EQUIPMENT_AND_INSTALLATION, 0.95, "TITLE_PRE_RESEARCH", "supply+installation")
        if has_design:
            return self._out(ProcurementScopeType.DESIGN_PROJECT, 0.95, "TITLE_PRE_RESEARCH", "explicit_design")
        if has_work:
            return self._out(ProcurementScopeType.WORKS_WITH_EMBEDDED_PRODUCTS, 0.95, "TITLE_PRE_RESEARCH", "explicit_works")
        if has_service and has_consumable:
            return self._out(ProcurementScopeType.SERVICE_WITH_CONSUMABLES, 0.90, "TITLE_PRE_RESEARCH", "service+consumables")
        if has_service and not has_supply:
            return self._out(ProcurementScopeType.PURE_SERVICE, 0.90, "TITLE_PRE_RESEARCH", "explicit_service")
        if has_supply and (has_product or product_okpd):
            return self._out(ProcurementScopeType.DIRECT_GOODS, 0.95, "TITLE+OKPD_PRE_RESEARCH", "explicit_supply+product_evidence")
        if has_product and product_okpd and not (has_work or has_design or has_service):
            return self._out(ProcurementScopeType.DIRECT_GOODS, 0.90, "SUBJECT+OKPD_PRE_RESEARCH", "product_subject+product_okpd")
        return self._out(ProcurementScopeType.UNKNOWN, 0.0, "PRE_RESEARCH_FAIL_CLOSED", "insufficient_pre_research_evidence")

    @staticmethod
    def _title(metadata: Dict[str, Any]) -> str:
        for key in ("title", "auction_name", "subject", "purchase_object"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return ""

    def _out(self, scope: ProcurementScopeType, confidence: float, method: str, reason: str) -> dict:
        return {
            "procurement_scope_type": scope.value,
            "scope_confidence": confidence,
            "scope_method": method,
            "scope_model_or_rule_version": f"{self.model}:{self.version}",
            "scope_evidence": {"reason": reason, "post_research_feature_count": 0},
            "procurement_scope_confidence": confidence,
            "procurement_scope_source": method,
            "procurement_scope_reason": reason,
            "procurement_scope_model": self.model,
            "procurement_scope_version": self.version,
            "procurement_scope_scored_at": datetime.now(timezone.utc).isoformat(),
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
        ProcurementScopeType.UNKNOWN.value: ProductRelation.UNKNOWN,
    }
    return mapping.get(scope_type_val, ProductRelation.UNKNOWN)
