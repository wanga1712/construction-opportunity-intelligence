"""Extraction of product observations from tabular estimate representations."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import uuid

from src.product_discovery.candidate_qualifier import qualify_section_candidates
from src.product_discovery.document_table_adapter import parse_numeric_cell
from src.product_discovery.dto import (
    ExtractedTableRow,
    ProductObservationDTO,
    RowType,
    UnitCategory,
)
from src.product_discovery.product_normalizer import ModelProductNormalizerV1
from src.product_discovery.unit_normalizer import normalize_unit


def extract_observations_from_table(
    rows: List[Union[Dict[str, Any], ExtractedTableRow]],
    procurement_id: int,
    document_id: Optional[str] = None,
    file_path: Optional[str] = None,
    sheet_name: Optional[str] = None,
    normalizer: Optional[ModelProductNormalizerV1] = None,
    okpd_code: str = "",
) -> List[ProductObservationDTO]:
    """Parses tabular estimate records into classified, normalized ProductObservationDTO instances."""
    norm = normalizer or ModelProductNormalizerV1()
    observations: List[ProductObservationDTO] = []

    for idx, row in enumerate(rows):
        if isinstance(row, ExtractedTableRow):
            col_map = row.column_mapping
            raw_cells = row.raw_cells
            
            raw_text = ""
            if "name" in col_map and col_map["name"] < len(raw_cells):
                raw_text = raw_cells[col_map["name"]].strip()
            if not raw_text:
                raw_text = row.raw_text.strip()

            raw_unit = raw_cells[col_map["unit"]].strip() if "unit" in col_map and col_map["unit"] < len(raw_cells) else ""
            qty = parse_numeric_cell(raw_cells[col_map["qty"]]) if "qty" in col_map and col_map["qty"] < len(raw_cells) else 0.0
            u_price = parse_numeric_cell(raw_cells[col_map["price"]]) if "price" in col_map and col_map["price"] < len(raw_cells) else 0.0
            tot_amt = parse_numeric_cell(raw_cells[col_map["amount"]]) if "amount" in col_map and col_map["amount"] < len(raw_cells) else 0.0
            if tot_amt == 0.0 and qty > 0 and u_price > 0:
                tot_amt = round(qty * u_price, 2)

            section = row.section_name or "Общий раздел"
            r_idx = row.row_index
            obs_key = row.observation_key or row.compute_observation_key()
            doc_id = row.document_id or document_id
            f_path = row.file_path or file_path
            s_name = row.sheet_name or sheet_name or "Лист 1"
            is_seed = False
        else:
            raw_text = str(
                row.get("name")
                or row.get("raw_text")
                or row.get("description")
                or row.get("item_name")
                or ""
            ).strip()
            raw_unit = str(row.get("unit") or row.get("unit_name") or row.get("unit_raw") or "")
            qty = parse_numeric_cell(row.get("quantity") or row.get("qty") or row.get("count"))
            u_price = parse_numeric_cell(row.get("unit_price") or row.get("price"))
            tot_amt = parse_numeric_cell(row.get("total_amount") or row.get("amount") or row.get("sum"))
            if tot_amt == 0.0 and qty > 0 and u_price > 0:
                tot_amt = round(qty * u_price, 2)

            section = str(row.get("section_name") or row.get("section") or "Общий раздел").strip()
            r_idx = idx
            obs_key = str(row.get("observation_key") or "")
            doc_id = document_id or str(row.get("document_id") or "")
            f_path = file_path or str(row.get("file_path") or "")
            s_name = sheet_name or str(row.get("sheet_name") or "Лист 1")
            is_seed = bool(row.get("is_seed", False))

        if not raw_text:
            continue

        u_cat = normalize_unit(raw_unit)
        decision = norm.normalize(
            raw_text=raw_text,
            okpd_code=okpd_code,
            section_name=section,
            unit_raw=raw_unit,
            total_amount=tot_amt,
        )

        obs_id = f"obs_{procurement_id}_{r_idx}_{str(uuid.uuid4())[:6]}"
        obs = ProductObservationDTO(
            observation_id=obs_id,
            procurement_id=procurement_id,
            document_id=doc_id,
            file_path=f_path,
            sheet_name=s_name,
            section_name=section,
            row_index=r_idx,
            raw_text=raw_text,
            normalized_name=decision.normalized_product_name,
            category_name=decision.category_name or decision.normalized_product_name,
            domain=decision.domain,
            subcategory_name=decision.subcategory_name,
            product_family=decision.product_family,
            row_type=decision.item_type,
            quantity=qty,
            unit_raw=raw_unit,
            unit_category=u_cat,
            unit_price=u_price,
            total_amount=tot_amt,
            is_seed=is_seed,
            confidence=decision.confidence,
            observation_key=obs_key,
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

