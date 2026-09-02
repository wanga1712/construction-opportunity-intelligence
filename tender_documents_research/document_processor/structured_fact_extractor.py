"""
R4 Structured Fact Extractor Module (V1).
Extracts raw documentary product/material/equipment/technology/work facts and exact quotes
from trusted V4 CONFIRMED candidate source document snapshots using qwen2.5:7b.

Guarantees:
- Model output is RAW-first (raw text + exact quotes). Model does NOT invent normalized commercial truth.
- Fail-closed validation via validate_extraction_run() BEFORE an extraction is marked COMPLETE.
- Strict input authority verification (no model call if input snapshot is invalid).
- Model identity verification (refuses calls if returned model is not qwen2.5:7b).
- All-or-nothing V1 safety: contract failure invalidates run to status=ERROR, entities=[].
"""

import json
import re
import hashlib
from typing import Any, Callable, Dict, List, Optional, Tuple

from tender_documents_research.document_processor.structured_fact_contract import (
    ExtractionRun,
    StructuredEntity,
    StructuredFieldEvidence,
    StructuredAttribute,
    STRUCTURED_EXTRACTOR_NAME,
    STRUCTURED_EXTRACTOR_VERSION,
    EXTRACTION_METHOD,
    PROMPT_VERSION,
    ALLOWED_ENTITY_TYPES,
    compute_sha256,
    verify_source_quote,
    normalize_whitespace,
    parse_numeric_values_from_string,
    validate_currency_consistency,
    validate_extraction_run,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import (
    CrmTaxonomyLoader,
)

STRUCTURED_EXTRACTOR_MODEL = "qwen2.5:7b"

def default_ai_caller(prompt: str, model: str = STRUCTURED_EXTRACTOR_MODEL, format_json: bool = True) -> Tuple[str, Dict[str, Any]]:
    """Default AI caller using src.services.ai_client.generate_with_meta()."""
    from src.services.ai_client import generate_with_meta
    return generate_with_meta(prompt, model=model, format_json=format_json, timeout=180)

class StructuredFactExtractor:
    def __init__(
        self,
        ai_caller: Optional[Callable[..., Tuple[str, Dict[str, Any]]]] = None,
        taxonomy_loader: Optional[CrmTaxonomyLoader] = None,
        model_name: str = STRUCTURED_EXTRACTOR_MODEL,
    ):
        self.ai_caller = ai_caller or default_ai_caller
        self.taxonomy_loader = taxonomy_loader
        self.model_name = model_name

    def get_category_names(self, category_code: str, subcategory_code: Optional[str] = None) -> Tuple[str, str]:
        """Resolves human-readable category and subcategory names from taxonomy loader."""
        cat_name = category_code
        subcat_name = subcategory_code or ""
        
        if self.taxonomy_loader:
            try:
                tax = self.taxonomy_loader.load_snapshot()
                cats = tax.categories if hasattr(tax, "categories") else {}
                if category_code in cats:
                    c_info = cats[category_code]
                    cat_name = c_info.get("name", category_code)
                    if subcategory_code and "subcategories" in c_info:
                        subcats = c_info["subcategories"]
                        if subcategory_code in subcats:
                            subcat_info = subcats[subcategory_code]
                            subcat_name = subcat_info.get("name", subcategory_code)
            except Exception:
                pass
        return (cat_name, subcat_name)

    def build_prompt(
        self,
        category_code: str,
        subcategory_code: Optional[str],
        source_text_snapshot: str,
    ) -> str:
        """
        Builds the raw-first provenance extraction prompt for qwen2.5:7b.
        Prompt is strictly taxonomy-agnostic (no specific brand/product few-shot examples).
        """
        cat_name, subcat_name = self.get_category_names(category_code, subcategory_code)
        
        prompt = f"""You are a precise documentary data extraction system for construction and commercial procurement documents.
Your task is to extract factual product, material, equipment, technology, or work items from the provided source document text.

Target Category: {cat_name} ({category_code})
Target Subcategory: {subcat_name or 'N/A'} ({subcategory_code or 'N/A'})

CRITICAL INSTRUCTIONS:
1. SOLE AUTHORITY: Extract ONLY facts directly supported by the source document text below. Never use outside knowledge, internet knowledge, or market associations.
2. RAW FACTS ONLY: Output raw text exactly as written in the source document. Do NOT invent normalized names or normalized commercial identities.
3. QUOTE REQUIREMENT: For EVERY non-null raw field and attribute, you MUST provide the exact verbatim "quote" from the source text where that value appears. Every quote MUST be an exact substring of the source text.
4. MISSING FACTS = NULL: If a field (manufacturer, brand, product_line, model_article, quantity, price, currency, attribute) is NOT explicitly stated in the source text, set its "raw" and "quote" to null. NEVER infer a missing manufacturer from brand or model names.
5. ENTITY TYPES: Allowed entity_type values are ONLY: "PRODUCT", "MATERIAL", "EQUIPMENT", "TECHNOLOGY", "WORK".
6. MULTIPLE OR ZERO ENTITIES: You may extract 0, 1, or multiple entities if multiple distinct items exist. If no separable entity is described in the text, return "entities": [].
7. JSON ONLY: Respond ONLY with a valid JSON object matching the JSON schema.

JSON SCHEMA:
{{
  "entities": [
    {{
      "entity_type": "PRODUCT|MATERIAL|EQUIPMENT|TECHNOLOGY|WORK",
      "product_name": {{ "raw": "exact raw product name", "quote": "exact source quote" }},
      "manufacturer": {{ "raw": "exact raw manufacturer or null", "quote": "exact quote or null" }},
      "brand": {{ "raw": "exact raw brand or null", "quote": "exact quote or null" }},
      "product_line": {{ "raw": "exact raw product line or null", "quote": "exact quote or null" }},
      "model_article": {{ "raw": "exact raw model or article or null", "quote": "exact quote or null" }},
      "quantity": {{ "raw": "exact raw quantity text e.g. '10 шт' or null", "unit_raw": "exact raw unit or null", "quote": "exact quote or null" }},
      "unit_price": {{ "raw": "exact raw price e.g. '4 500,00 руб.' or null", "quote": "exact quote or null" }},
      "total_price": {{ "raw": "exact raw price or null", "quote": "exact quote or null" }},
      "currency": {{ "raw": "exact raw currency e.g. 'руб.' or null", "quote": "exact quote or null" }},
      "attributes": [
        {{
          "name": "characteristic name e.g. Мощность",
          "raw_value": "exact raw value e.g. 40 Вт",
          "unit_raw": "raw unit e.g. Вт or null",
          "quote": "exact source quote"
        }}
      ]
    }}
  ]
}}

SOURCE DOCUMENT TEXT:
\"\"\"
{source_text_snapshot}
\"\"\"
"""
        return prompt

    def parse_response(
        self,
        raw_response_text: str,
        source_text_snapshot: str,
    ) -> Tuple[List[StructuredEntity], Optional[str]]:
        """
        Parses raw model JSON output into StructuredEntity list.
        Validates exact quote containment against source_text_snapshot.
        Applies deterministic fail-closed post-extraction normalization helpers.
        
        Returns (entities, error_code). If error_code is not None, parsing failed.
        """
        try:
            # Clean JSON markdown fences if present
            cleaned_text = raw_response_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()

            data = json.loads(cleaned_text)
        except Exception as e:
            return ([], "INVALID_JSON")

        if not isinstance(data, dict) or "entities" not in data:
            return ([], "INVALID_SCHEMA")

        raw_entities = data.get("entities")
        if not isinstance(raw_entities, list):
            return ([], "INVALID_SCHEMA")

        entities: List[StructuredEntity] = []

        for idx, ent_dict in enumerate(raw_entities):
            if not isinstance(ent_dict, dict):
                return ([], "INVALID_ENTITY_SHAPE")

            entity_type = str(ent_dict.get("entity_type", "PRODUCT")).upper()
            if entity_type not in ALLOWED_ENTITY_TYPES:
                return ([], "INVALID_ENTITY_TYPE")

            prod_dict = ent_dict.get("product_name") or {}
            p_raw = prod_dict.get("raw")
            p_quote = prod_dict.get("quote")

            if not p_raw or not str(p_raw).strip():
                return ([], "MISSING_PRODUCT_NAME")
            if not p_quote or not verify_source_quote(p_quote, source_text_snapshot):
                return ([], "PRODUCT_NAME_QUOTE_INVALID")
            if normalize_whitespace(p_raw) not in normalize_whitespace(p_quote):
                return ([], "PRODUCT_NAME_VALUE_NOT_IN_QUOTE")

            entity_anchor_quote = p_quote
            field_evidence: List[StructuredFieldEvidence] = [
                StructuredFieldEvidence(field_name="product_name", source_quote=p_quote)
            ]

            # Core fields helper
            core_fields = {
                "manufacturer": "manufacturer_raw",
                "brand": "brand_raw",
                "product_line": "product_line_raw",
                "model_article": "model_article_raw",
                "unit_price": "unit_price_raw",
                "total_price": "total_price_raw",
                "currency": "currency_raw",
            }
            extracted_raw: Dict[str, Optional[str]] = {}

            for field_key, entity_attr in core_fields.items():
                f_dict = ent_dict.get(field_key) or {}
                raw_v = f_dict.get("raw")
                quote_v = f_dict.get("quote")
                if raw_v and str(raw_v).strip():
                    if not quote_v or not verify_source_quote(quote_v, source_text_snapshot):
                        return ([], f"{field_key.upper()}_QUOTE_INVALID")
                    if normalize_whitespace(raw_v) not in normalize_whitespace(quote_v):
                        return ([], f"{field_key.upper()}_VALUE_NOT_IN_QUOTE")
                    extracted_raw[entity_attr] = str(raw_v).strip()
                    field_evidence.append(StructuredFieldEvidence(field_name=field_key, source_quote=quote_v))
                else:
                    extracted_raw[entity_attr] = None

            # Quantity handling
            q_dict = ent_dict.get("quantity") or {}
            q_raw = q_dict.get("raw")
            q_unit_raw = q_dict.get("unit_raw")
            q_quote = q_dict.get("quote")
            
            quantity_raw = None
            quantity_value = None
            quantity_unit_raw = None
            
            if q_raw and str(q_raw).strip():
                if not q_quote or not verify_source_quote(q_quote, source_text_snapshot):
                    return ([], "QUANTITY_QUOTE_INVALID")
                if normalize_whitespace(q_raw) not in normalize_whitespace(q_quote):
                    return ([], "QUANTITY_VALUE_NOT_IN_QUOTE")
                
                quantity_raw = str(q_raw).strip()
                field_evidence.append(StructuredFieldEvidence(field_name="quantity", source_quote=q_quote))
                
                # Fail-closed deterministic numeric parsing: ONLY if uniquely parseable!
                nums = parse_numeric_values_from_string(quantity_raw)
                if len(nums) == 1:
                    quantity_value = nums[0]
                else:
                    quantity_value = None  # Multiple or 0 parseable numbers -> NULL!

                if q_unit_raw and str(q_unit_raw).strip():
                    q_unit_str = str(q_unit_raw).strip()
                    norm_u = normalize_whitespace(q_unit_str)
                    if norm_u in normalize_whitespace(quantity_raw) or norm_u in normalize_whitespace(q_quote):
                        quantity_unit_raw = q_unit_str
                    else:
                        return ([], "QUANTITY_UNIT_NOT_IN_QUOTE")

            # Deterministic numeric parsing for price fields
            unit_price_value = None
            if extracted_raw["unit_price_raw"]:
                nums = parse_numeric_values_from_string(extracted_raw["unit_price_raw"])
                if len(nums) == 1:
                    unit_price_value = nums[0]

            total_price_value = None
            if extracted_raw["total_price_raw"]:
                nums = parse_numeric_values_from_string(extracted_raw["total_price_raw"])
                if len(nums) == 1:
                    total_price_value = nums[0]

            # Currency code check
            currency_code = None
            if extracted_raw["currency_raw"]:
                if validate_currency_consistency(extracted_raw["currency_raw"], "RUB"):
                    currency_code = "RUB"

            # Attributes parsing
            raw_attrs = ent_dict.get("attributes") or []
            attributes: List[StructuredAttribute] = []
            
            if isinstance(raw_attrs, list):
                for a_idx, a_dict in enumerate(raw_attrs):
                    if not isinstance(a_dict, dict):
                        return ([], "INVALID_ATTRIBUTE_SHAPE")
                    a_name = a_dict.get("name")
                    a_raw = a_dict.get("raw_value")
                    a_quote = a_dict.get("quote")
                    a_unit = a_dict.get("unit_raw")

                    if not a_name or not str(a_name).strip() or not a_raw or not str(a_raw).strip():
                        return ([], "ATTRIBUTE_MISSING_NAME_OR_VALUE")
                    if not a_quote or not verify_source_quote(a_quote, source_text_snapshot):
                        return ([], "ATTRIBUTE_QUOTE_INVALID")
                    if normalize_whitespace(a_raw) not in normalize_whitespace(a_quote):
                        return ([], "ATTRIBUTE_VALUE_NOT_IN_QUOTE")

                    norm_a_name = re.sub(r"[^\w]+", "_", str(a_name).lower()).strip("_")
                    if not norm_a_name:
                        norm_a_name = f"attribute_{a_idx+1}"

                    a_num_value = None
                    a_nums = parse_numeric_values_from_string(str(a_raw))
                    if len(a_nums) == 1:
                        a_num_value = a_nums[0]

                    a_unit_raw = None
                    if a_unit and str(a_unit).strip():
                        u_str = str(a_unit).strip()
                        norm_u = normalize_whitespace(u_str)
                        if norm_u in normalize_whitespace(a_raw) or norm_u in normalize_whitespace(a_quote):
                            a_unit_raw = u_str
                        else:
                            return ([], "ATTRIBUTE_UNIT_NOT_IN_QUOTE")

                    attributes.append(
                        StructuredAttribute(
                            attribute_name=str(a_name).strip(),
                            attribute_name_normalized=norm_a_name,
                            raw_value=str(a_raw).strip(),
                            source_quote=a_quote,
                            numeric_value=a_num_value,
                            unit_raw=a_unit_raw,
                        )
                    )

            ent = StructuredEntity(
                product_name_raw=p_raw.strip(),
                source_quote=entity_anchor_quote,
                entity_type=entity_type,
                manufacturer_raw=extracted_raw["manufacturer_raw"],
                brand_raw=extracted_raw["brand_raw"],
                product_line_raw=extracted_raw["product_line_raw"],
                model_article_raw=extracted_raw["model_article_raw"],
                quantity_raw=quantity_raw,
                quantity_value=quantity_value,
                quantity_unit_raw=quantity_unit_raw,
                unit_price_raw=extracted_raw["unit_price_raw"],
                unit_price_value=unit_price_value,
                total_price_raw=extracted_raw["total_price_raw"],
                total_price_value=total_price_value,
                currency_raw=extracted_raw["currency_raw"],
                currency_code=currency_code,
                field_evidence=field_evidence,
                attributes=attributes,
            )
            entities.append(ent)

        return (entities, None)

    def extract_candidate(self, candidate: Dict[str, Any]) -> ExtractionRun:
        """
        Executes structured extraction for a canonical candidate row.
        
        Fail-Closed Authority Checks:
        - Must be CONFIRMED, context_validator v4 QWEN_CONTEXT_V4, source available & eligible, valid SHA.
        """
        detail_id = candidate.get("detail_id") or 0
        procurement_id = candidate.get("procurement_id") or 0
        category_code = candidate.get("category_code") or ""
        subcategory_code = candidate.get("subcategory_code")
        snapshot = candidate.get("source_text_snapshot") or ""
        snapshot_sha = candidate.get("source_text_sha256") or ""
        calc_sha = compute_sha256(snapshot) if snapshot else ""

        run = ExtractionRun(
            detail_id=detail_id,
            procurement_id=procurement_id,
            category_code=category_code,
            subcategory_code=subcategory_code,
            match_id=candidate.get("match_id"),
            queue_id=candidate.get("queue_id"),
            document_name=candidate.get("document_name"),
            archive_member_path=candidate.get("archive_member_path"),
            page_or_sheet=candidate.get("page_or_sheet"),
            row_number=candidate.get("row_number"),
            source_text_snapshot=snapshot,
            source_text_sha256=snapshot_sha,
            source_validator_name=candidate.get("source_validator_name") or "context_validator",
            source_validator_version=candidate.get("source_validator_version") or "v4",
            source_validation_method=candidate.get("source_validation_method") or "QWEN_CONTEXT_V4",
            extractor_name=STRUCTURED_EXTRACTOR_NAME,
            extractor_version=STRUCTURED_EXTRACTOR_VERSION,
            extraction_method=EXTRACTION_METHOD,
            prompt_version=PROMPT_VERSION,
            model_name=self.model_name,
            status="PENDING",
        )

        # 1. Authority Pre-checks (Section 5)
        if (
            candidate.get("validation_status") != "CONFIRMED"
            or candidate.get("source_validator_name") != "context_validator"
            or str(candidate.get("source_validator_version")).lower() != "v4"
            or str(candidate.get("source_validation_method")).upper() != "QWEN_CONTEXT_V4"
            or not candidate.get("source_available")
            or not candidate.get("extraction_eligible")
            or not snapshot
            or snapshot_sha != calc_sha
        ):
            run.status = "ERROR"
            run.error_code = "INVALID_INPUT_AUTHORITY"
            run.error_message = "Candidate failed input authority pre-checks"
            return run

        # 2. Build Prompt
        prompt = self.build_prompt(category_code, subcategory_code, snapshot)

        # 3. Model Call & Model Identity Check (Section 22)
        try:
            raw_text, meta = self.ai_caller(prompt, model=self.model_name, format_json=True)
        except Exception as e:
            run.status = "ERROR"
            run.error_code = "MODEL_EXCEPTION"
            run.error_message = str(e)
            return run

        ret_model = str(meta.get("model", "")).lower()
        if self.model_name.lower() not in ret_model and "qwen2.5:7b" not in ret_model:
            run.status = "ERROR"
            run.error_code = "WRONG_MODEL"
            run.error_message = f"Expected model {self.model_name}, got returned model meta '{ret_model}'"
            run.raw_response = {"raw_text": raw_text, "meta": meta}
            return run

        run.raw_response = {
            "raw_text": raw_text,
            "meta": meta,
            "prompt_sha256": compute_sha256(prompt),
            "source_sha256": snapshot_sha,
        }

        # 4. Parse Response
        entities, parse_err = self.parse_response(raw_text, snapshot)
        if parse_err:
            run.status = "ERROR"
            run.error_code = parse_err
            run.error_message = f"Parser failed with error code: {parse_err}"
            run.entities = []
            return run

        run.entities = entities

        # 5. Contract Validation & All-or-Nothing V1 Safety (Section 19 & 20)
        is_valid, errors = validate_extraction_run(run)
        if not is_valid:
            run.status = "ERROR"
            run.error_code = "CONTRACT_VALIDATION_FAILED"
            run.error_message = "; ".join(errors)
            run.entities = []
            return run

        # 6. Final Status (Section 21)
        if len(entities) >= 1:
            run.status = "COMPLETE"
        else:
            run.status = "EMPTY"

        return run
