# MODEL_INPUT_FIELD_AUDIT.md

WIP: Phase 8 audit only. Fields not changed.

MODEL_INPUT_VERSION=`V3_ROUTING_MODEL_INPUT_V3`

| field | class |
| --- | --- |
| model_input_version | NOT_REQUIRED_FOR_ROUTING |
| procurement_id | NOT_REQUIRED_FOR_ROUTING |
| procurement_number | NOT_REQUIRED_FOR_ROUTING |
| source_contour | SEMANTIC_CLASSIFICATION_REQUIRED |
| source_table | NOT_REQUIRED_FOR_ROUTING |
| source_id | NOT_REQUIRED_FOR_ROUTING |
| source_origin | NOT_REQUIRED_FOR_ROUTING |
| title | SEMANTIC_CLASSIFICATION_REQUIRED |
| official_description | SEMANTIC_CLASSIFICATION_REQUIRED |
| normalized_lifecycle | LIFECYCLE_ONLY |
| source_start_date | LIFECYCLE_ONLY |
| source_end_date | LIFECYCLE_ONLY |
| procurement_start_at | LIFECYCLE_ONLY |
| procurement_end_at | LIFECYCLE_ONLY |
| procurement_start_at_provenance | LIFECYCLE_ONLY |
| procurement_end_at_provenance | LIFECYCLE_ONLY |
| published_at | LIFECYCLE_ONLY |
| published_at_provenance | LIFECYCLE_ONLY |
| source_created_at | LIFECYCLE_ONLY |
| procurement_duration_days | LIFECYCLE_ONLY |
| remaining_days | LATER_SCORING_ONLY |
| remaining_ratio | LATER_SCORING_ONLY |
| deadline_pressure | LATER_SCORING_ONLY |
| procurement_age_days | LATER_SCORING_ONLY |
| award_age_days | LATER_SCORING_ONLY |
| execution_remaining_days | LATER_SCORING_ONLY |
| commercial_timing_value | LATER_SCORING_ONLY |
| commercial_timing_version | LATER_SCORING_ONLY |
| commercial_timing_confidence | LATER_SCORING_ONLY |
| commercial_timing_start_provenance | LATER_SCORING_ONLY |
| source_delivery_start_date | LIFECYCLE_ONLY |
| source_delivery_end_date | LIFECYCLE_ONLY |
| delivery_start_at | LIFECYCLE_ONLY |
| delivery_end_at | LIFECYCLE_ONLY |
| customer_name | UI_ONLY |
| customer_inn | NOT_REQUIRED_FOR_ROUTING |
| purchasing_organization | UI_ONLY |
| winner_name | LIFECYCLE_ONLY |
| winner_inn | LIFECYCLE_ONLY |
| winner_role | LIFECYCLE_ONLY |
| award_at | LIFECYCLE_ONLY |
| initial_price | LATER_SCORING_ONLY |
| final_contract_price | LATER_SCORING_ONLY |
| price_reduction_percent | LATER_SCORING_ONLY |
| contract_execution_end_at | LIFECYCLE_ONLY |
| execution_active | LIFECYCLE_ONLY |
| primary_commercial_region | NOT_REQUIRED_FOR_ROUTING |
| region_provenance | NOT_REQUIRED_FOR_ROUTING |
| okpd_codes | COMMERCIAL_MAPPING_REQUIRED |
| okpd_names | COMMERCIAL_MAPPING_REQUIRED |
| okpd_hierarchy | COMMERCIAL_MAPPING_REQUIRED |
| COMMERCIAL_PRODUCT_PRIORS | POTENTIALLY_HARMFUL_ANCHOR |
| CONTEXTUAL_RESEARCH_PRIORS | POTENTIALLY_HARMFUL_ANCHOR |
| DIRECT_CABLE_EXPECTED_RESULT | POTENTIALLY_HARMFUL_ANCHOR |
| source_card_url | UI_ONLY |
| source_card_url_type | UI_ONLY |
| document_link_count | POTENTIALLY_HARMFUL_ANCHOR |
| unique_document_count | POTENTIALLY_HARMFUL_ANCHOR |

## Document boundary

- **DOCUMENT_CONTENT_SENT_TO_ROUTING_MODEL**=`NO`
- **DOCUMENT_TEXT_SENT_TO_ROUTING_MODEL**=`NO`
- **DOCUMENT_NAMES_SENT_TO_ROUTING_MODEL**=`NO`
- **DOCUMENT_EVIDENCE_SENT_TO_ROUTING_MODEL**=`NO`
- **WHAT_IS_SENT**=`['document_link_count', 'unique_document_count']`
- **NOTE**=`Canonical card may resolve document_links_summary (names/URLs) but V3_ROUTING_MODEL_INPUT_V3 excludes link arrays; only counts enter the prompt JSON.`

Fields the prompt still asks that need unseen documents:

- document_research_priority
- confirmation_required for CONTEXTUAL_RESEARCH_PRIOR
- evidence that products are confirmed in documents (Q7)
- MODE B object hypotheses framed as requiring document confirmation
