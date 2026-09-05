# CRM V3 Category Opportunity Cards and Multi-Medal Output (WIP Specification)

## Overview
This document specifies the technical design, data authority, read model, and Streamlit CRM presentation for multi-medal commercial category opportunities per procurement.

---

## 1. Core Invariants & Separation of Priorities

The system explicitly distinguishes three independent priority/medal concepts:

| Priority / Medal Concept | Authority & Meaning | Stage / Timing |
| :--- | :--- | :--- |
| **`research_prior_band`** | Raw Stage 1 model prediction (`GOLD`, `SILVER`, `BRONZE`, `WOOD`). Answers: *"Is this procurement worth researching fast?"* | Pre-Research |
| **`effective_service_band`** | Technical queue scheduling priority (e.g. `GOLD` via `DIRECT_GOODS` $\ge 50\,000$ RUB override). Answers: *"When should the worker claim this task?"* | Pre-Research / Queue Claim |
| **`category_commercial_medal`** | Commercial medal assigned to a specific confirmed product category (`GOLD`, `SILVER`, `BRONZE`, `WOOD`). Answers: *"What is the commercial value of this specific product category found in this procurement?"* | Post-Research / Confirmed |

### Rule: No Max-Medal Collapse (`MAX_MEDAL_COLLAPSE = NO`)
A single procurement containing multiple confirmed categories (e.g. Linoleum `GOLD`, Lighting `GOLD`, Curbstone `WOOD`) MUST NOT be collapsed into `PROCUREMENT = GOLD` losing all lower-medal categories. The primary commercial entity is `PROCUREMENT x PRODUCT_CATEGORY`.

---

## 2. Canonical Read Model: `CategoryOpportunity`

Service authority: `src/services/category_opportunity_service.py`

### Data Structure:
```python
@dataclass
class CategoryOpportunity:
    procurement_id: int
    category_id: int
    category_name: str
    subcategory_id: Optional[int]
    subcategory_name: Optional[str]
    commercial_medal: str  # GOLD, SILVER, BRONZE, WOOD, UNASSIGNED
    commercial_state: str  # CONFIRMED, UNREVIEWED, etc.
    medal_authority: str   # EXPERT, SYSTEM_DEFAULT
    product_relation: str  # PRIMARY_SUBJECT, EMBEDDED_IN_WORKS, SPECIFIED_IN_PROJECT, etc.
    material_count: int
    position_count: int
    quantities_by_unit: List[Dict[str, Any]]  # [{'unit': 'm2', 'quantity': 12450, 'positions': 8}]
    potential_supply_value_rub: Optional[float]
    potential_supply_value_method: str  # EXPLICIT_LINE_TOTAL, EXPLICIT_CATEGORY_TOTAL, DERIVED_QUANTITY_X_UNIT_PRICE, DIRECT_SINGLE_CATEGORY_NMCK_UPPER_BOUND, NOT_AVAILABLE
    evidence_count: int
    latest_confirmed_at: Optional[str]
```

---

## 3. UI Presentation Design (`🎯 НАЙДЕНО ПОСЛЕ ИССЛЕДОВАНИЯ`)

Surfaced below the procurement overview on Streamlit procurement cards:
- **Neutral Outer Card**: Procurement outer card remains neutral to avoid false gold-washing when mixed medals exist (`GOLD` + `WOOD`).
- **Category Subcards**: Rendered with category-specific medal colors (`🥇 GOLD`, `🥈 SILVER`, `🥉 BRONZE`, `🪵 WOOD`).
- **Drilldown Section**: Expandable table listing distinct materials, quantities by unit, potential supply values, and physical document provenance (document name, archive path, page/sheet, exact quote).
- **Filters**: Surfaced on procurement list view:
  - `Category` filter
  - `Commercial Medal` filter (`All`, `GOLD`, `SILVER`, `BRONZE`, `WOOD`, `Unassigned`)
  - `Confirmed Only` toggle (`✓ Только подтвержденные категории`).

---

## 4. Safety & Performance

- **Zero N+1 Queries**: Bulk fetching category opportunities across active page procurements using a single `WHERE procurement_id = ANY(...)` query.
- **Data Immuntability**: `research_prior_band`, `effective_service_band`, and Stage 1 model outputs remain strictly unchanged (`STAGE1_FIELDS_MUTATED = 0`).
