"""Candidate product qualification and noise filtering within estimate sections."""

from __future__ import annotations

from typing import List, Optional, Tuple

from src.product_discovery.dto import ProductObservationDTO, RowType
from src.product_discovery.unit_normalizer import are_units_compatible


ELIGIBLE_ROW_TYPES = {RowType.PRODUCT, RowType.EQUIPMENT, RowType.MATERIAL}


def qualify_section_candidates(
    seed: Optional[ProductObservationDTO],
    observations: List[ProductObservationDTO],
    min_seed_amount_ratio: float = 0.50,
    min_quantity_similarity: float = 0.70,
    min_section_value_share: float = 0.05,
    noise_floor_amount: float = 50_000.0,
) -> List[Tuple[ProductObservationDTO, str]]:
    """Evaluates companion observations in an estimate section and qualifies co-product candidates."""
    if not observations:
        return []

    # Calculate total product/equipment/material amount in this section
    section_product_amount = sum(
        obs.total_amount for obs in observations
        if obs.row_type in ELIGIBLE_ROW_TYPES
    )

    qualified: List[Tuple[ProductObservationDTO, str]] = []

    for cand in observations:
        # Skip seed itself if present
        if seed and (cand.observation_id == seed.observation_id or cand.is_seed):
            continue

        # 1. Row type filter: strictly exclude WORK, SERVICE, MACHINE, UNKNOWN
        if cand.row_type not in ELIGIBLE_ROW_TYPES:
            continue

        # 2. Noise floor suppression (e.g. small hardware/consumables with low monetary share)
        if section_product_amount > 1_000_000.0:
            share = cand.total_amount / max(1.0, section_product_amount)
            if share < 0.02 and cand.total_amount < noise_floor_amount:
                continue

        # 3. Seed-guided qualification
        if seed:
            matched_reasons = []

            # Condition A: Monetary amount >= seed amount
            if cand.total_amount >= seed.total_amount and cand.total_amount > 0:
                matched_reasons.append("CONDITION_A:AMOUNT_GE_SEED")

            # Condition B: Compatible unit and quantity >= seed quantity
            if are_units_compatible(cand.unit_category, seed.unit_category):
                if cand.quantity >= seed.quantity and cand.quantity > 0:
                    matched_reasons.append("CONDITION_B:QUANTITY_GE_SEED")

            # Condition C: Amount ratio >= min_seed_amount_ratio (e.g. >= 0.50)
            if seed.total_amount > 0:
                amt_ratio = cand.total_amount / seed.total_amount
                if amt_ratio >= min_seed_amount_ratio:
                    matched_reasons.append(f"CONDITION_C:AMOUNT_RATIO_{amt_ratio:.2f}")

            # Condition D: Compatible unit and quantity similarity >= min_quantity_similarity (e.g. >= 0.70)
            if are_units_compatible(cand.unit_category, seed.unit_category):
                max_q = max(cand.quantity, seed.quantity)
                min_q = min(cand.quantity, seed.quantity)
                if max_q > 0:
                    q_sim = min_q / max_q
                    if q_sim >= min_quantity_similarity:
                        matched_reasons.append(f"CONDITION_D:QTY_SIM_{q_sim:.2f}")

            # Condition E: Share of section total >= min_section_value_share (e.g. >= 0.10)
            if section_product_amount > 0:
                sec_share = cand.total_amount / section_product_amount
                if sec_share >= min_section_value_share:
                    matched_reasons.append(f"CONDITION_E:SECTION_SHARE_{sec_share:.2f}")

            if matched_reasons:
                cand.seed_observation_id = seed.observation_id
                qualified.append((cand, " | ".join(matched_reasons)))

        # 4. Seedless qualification
        else:
            if section_product_amount > 0:
                sec_share = cand.total_amount / section_product_amount
                if sec_share >= min_section_value_share or cand.total_amount >= 500_000.0:
                    reason = f"SEEDLESS_DISCOVERY:SECTION_SHARE_{sec_share:.2f}"
                    qualified.append((cand, reason))

    return qualified
