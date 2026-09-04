"""Extraction of product observations from tabular estimate representations."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

from src.product_discovery.candidate_qualifier import qualify_section_candidates
from src.product_discovery.dto import ProductObservationDTO, RowType, UnitCategory
from src.product_discovery.product_normalizer import normalize_product_name
from src.product_discovery.row_classifier import classify_row
from src.product_discovery.unit_normalizer import normalize_unit


def extract_observations_from_table(
    rows: List[Dict[str, Any]],
    procurement_id: int,
    document_id: Optional[str] = None,
    file_path: Optional[str] = None,
    sheet_name: Optional[str] = None,
) -> List[ProductObservationDTO]:
    """Parses tabular estimate dictionary records into classified ProductObservationDTO instances."""
    observations: List[ProductObservationDTO] = []

    for idx, row in enumerate(rows):
        raw_text = str(
            row.get("name")
            or row.get("raw_text")
            or row.get("description")
            or row.get("item_name")
            or ""
        ).strip()
        if not raw_text:
            continue

        raw_unit = str(row.get("unit") or row.get("unit_name") or row.get("unit_raw") or "")
        u_cat = normalize_unit(raw_unit)

        try:
            qty = float(row.get("quantity") or row.get("qty") or row.get("count") or 0.0)
        except (ValueError, TypeError):
            qty = 0.0

        try:
            u_price = float(row.get("unit_price") or row.get("price") or 0.0)
        except (ValueError, TypeError):
            u_price = 0.0

        try:
            tot_amt = float(row.get("total_amount") or row.get("amount") or row.get("sum") or 0.0)
        except (ValueError, TypeError):
            tot_amt = round(qty * u_price, 2)

        section = str(row.get("section_name") or row.get("section") or "Общий раздел").strip()
        r_type = classify_row(raw_text, raw_unit, tot_amt)
        norm_name = normalize_product_name(raw_text)

        obs_id = str(row.get("observation_id") or f"obs_{procurement_id}_{idx}_{str(uuid.uuid4())[:6]}")
        is_seed = bool(row.get("is_seed", False))

        obs = ProductObservationDTO(
            observation_id=obs_id,
            procurement_id=procurement_id,
            document_id=document_id,
            file_path=file_path,
            sheet_name=sheet_name or str(row.get("sheet_name") or "Лист 1"),
            section_name=section,
            row_index=idx,
            raw_text=raw_text,
            normalized_name=norm_name,
            category_name=norm_name,
            row_type=r_type,
            quantity=qty,
            unit_raw=raw_unit,
            unit_category=u_cat,
            unit_price=u_price,
            total_amount=tot_amt,
            is_seed=is_seed,
            confidence=float(row.get("confidence", 0.8)),
        )
        observations.append(obs)

    return observations


def discover_coproducts_from_section(
    observations: List[ProductObservationDTO],
    seed_predicate: Optional[Callable[[ProductObservationDTO], bool]] = None,
) -> Tuple[Optional[ProductObservationDTO], List[Tuple[ProductObservationDTO, str]]]:
    """Finds seed observation if any, and qualifies companion co-product candidates."""
    seed_obs = None
    if seed_predicate:
        for obs in observations:
            if seed_predicate(obs):
                obs.is_seed = True
                seed_obs = obs
                break

    if seed_obs is None:
        for obs in observations:
            if obs.is_seed:
                seed_obs = obs
                break

    qualified = qualify_section_candidates(seed=seed_obs, observations=observations)
    return seed_obs, qualified
