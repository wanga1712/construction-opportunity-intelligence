"""Co-product graph construction and empirical conditional association scoring."""

from __future__ import annotations

from collections import defaultdict
import statistics
from typing import Any, Dict, List, Set, Tuple

from src.product_discovery.dto import CategoryRelationDTO, ProductObservationDTO, RowType
from src.product_discovery.unit_normalizer import are_units_compatible


ELIGIBLE_ROW_TYPES = {RowType.PRODUCT, RowType.EQUIPMENT, RowType.MATERIAL}


def build_coproduct_relations(
    observations: List[ProductObservationDTO],
    min_co_occurrences: int = 1,
) -> List[CategoryRelationDTO]:
    """Computes empirical co-occurrence graph, conditional probabilities, and quantitative ratios."""
    # Filter observations to eligible product/material items with valid category
    valid_obs = [
        o for o in observations
        if o.row_type in ELIGIBLE_ROW_TYPES and o.category_name
    ]

    # Group by procurement section context
    section_groups: Dict[Tuple[int, str, str], List[ProductObservationDTO]] = defaultdict(list)
    cat_occurrences: Dict[str, int] = defaultdict(int)
    cat_procurements: Dict[str, Set[int]] = defaultdict(set)

    for o in valid_obs:
        key = (o.procurement_id, o.sheet_name or "", o.section_name or "")
        section_groups[key].append(o)
        cat_occurrences[o.category_name] += 1
        cat_procurements[o.category_name].add(o.procurement_id)

    # Co-occurrence statistics: (cat_a, cat_b) -> metrics
    co_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    amount_ratios: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    quantity_ratios: Dict[Tuple[str, str], List[float]] = defaultdict(list)

    for group in section_groups.values():
        # Get unique categories in this section
        cats_in_group = {o.category_name for o in group}
        if len(cats_in_group) < 2:
            continue

        # Map each category to its highest-value observation in section
        cat_top_obs: Dict[str, ProductObservationDTO] = {}
        for o in group:
            if o.category_name not in cat_top_obs or o.total_amount > cat_top_obs[o.category_name].total_amount:
                cat_top_obs[o.category_name] = o

        for cat_a in cats_in_group:
            for cat_b in cats_in_group:
                if cat_a == cat_b:
                    continue

                obs_a = cat_top_obs[cat_a]
                obs_b = cat_top_obs[cat_b]

                pair = (cat_a, cat_b)
                co_counts[pair] += 1

                if obs_a.total_amount > 0:
                    amount_ratios[pair].append(obs_b.total_amount / obs_a.total_amount)

                if are_units_compatible(obs_a.unit_category, obs_b.unit_category):
                    if obs_a.quantity > 0:
                        quantity_ratios[pair].append(obs_b.quantity / obs_a.quantity)

    relations: List[CategoryRelationDTO] = []

    for (cat_a, cat_b), count in co_counts.items():
        if count < min_co_occurrences:
            continue

        total_a = cat_occurrences.get(cat_a, 1)
        prob_b_given_a = min(1.0, count / float(total_a))

        amt_list = amount_ratios.get((cat_a, cat_b), [])
        med_amt_ratio = statistics.median(amt_list) if amt_list else 0.0

        qty_list = quantity_ratios.get((cat_a, cat_b), [])
        med_qty_ratio = statistics.median(qty_list) if qty_list else 0.0

        relations.append(
            CategoryRelationDTO(
                category_a=cat_a,
                category_b=cat_b,
                co_occurrence_count=count,
                conditional_prob_b_given_a=round(prob_b_given_a, 4),
                median_amount_ratio=round(med_amt_ratio, 4),
                median_quantity_ratio=round(med_qty_ratio, 4),
            )
        )

    # Sort descending by co_occurrence_count, then conditional probability
    relations.sort(key=lambda r: (r.co_occurrence_count, r.conditional_prob_b_given_a), reverse=True)
    return relations
