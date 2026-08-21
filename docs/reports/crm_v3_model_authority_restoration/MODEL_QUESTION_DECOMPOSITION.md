# MODEL_QUESTION_DECOMPOSITION.md

WIP: Phase 8. Enumerated from production `prompt.py` (v5) and frozen SHADOW `prompt_v6_1.py`.

| QUESTION_ID | CLASS | OUTPUT_FIELD | TAXONOMY | DOCS | PRE_DOC_OK |
| --- | --- | --- | --- | --- | --- |
| Q1_PROCUREMENT_FORM | SEMANTIC_CLASSIFICATION | procurement_form | no | no | yes |
| Q2_OBJECT_CLASSIFICATION | FACT_EXTRACTION | object_classification | no | no | yes |
| Q3_ACTUAL_PURCHASE_ITEM | FACT_EXTRACTION | object_classification.object_subtype + reason_codes | no | no | yes |
| Q4_REGISTRY_CATEGORY_MAP | COMMERCIAL_TAXONOMY_MAPPING | commercial_category_hypotheses[].category_code | yes | no | yes |
| Q5_OPPORTUNITY_TRACK | SEMANTIC_CLASSIFICATION | commercial_category_hypotheses[].opportunity_track | yes | no | partial |
| Q6_OBJECT_PRIOR_PRODUCTS | OBJECT_CONTEXT_PREDICTION | commercial_category_hypotheses (contextual) + object_context | yes | no | yes |
| Q7_DOCUMENT_CONFIRMED_PRODUCTS | RESEARCH_PLANNING | evidence_role / confirmation_required / document_research_priority | yes | yes | no |
| Q8_ABSTENTION | ABSTENTION | empty_hypothesis_status + empty_hypothesis_reason_codes | yes | no | yes |
| Q9_RESEARCH_ACTION | RESEARCH_PLANNING | overall_research_action + document_research_priority | no | no | yes |
| Q10_MATERIAL_SIGNALS | FACT_EXTRACTION | material_signals / brands / work_methods / application_areas | no | no | yes |

## Plain-Russian questions

### Q1_PROCUREMENT_FORM
Какая форма закупки (поставка товара / СМР / проектирование / услуги / иное)?

### Q2_OBJECT_CLASSIFICATION
Что это за объект/товар и на какой стадии работ?

### Q3_ACTUAL_PURCHASE_ITEM
Что фактически закупается по заголовку/ОКПД?

### Q4_REGISTRY_CATEGORY_MAP
Какой ACTIVE код коммерческого реестра соответствует закупаемому?

### Q5_OPPORTUNITY_TRACK
Это прямая поставка или встроенный/проектный материал объекта?

### Q6_OBJECT_PRIOR_PRODUCTS
Какие продукты реестра правдоподобны на этом объекте строительства/проектирования?

### Q7_DOCUMENT_CONFIRMED_PRODUCTS
Какие продукты уже подтверждены документами?

### Q8_ABSTENTION
Нужно ли отказаться от гипотез и с каким статусом пустоты?

### Q9_RESEARCH_ACTION
Какую глубину исследования документов назначить?

### Q10_MATERIAL_SIGNALS
Какие материальные/брендовые сигналы видны из карточки?

## Critical semantic split

- **ACTUAL_PURCHASE_VS_REGISTRY_MAPPING_MIXED**=`YES`
- **ACTUAL_PURCHASE_VS_OBJECT_PRIOR_MIXED**=`YES`
- **OBJECT_PRIOR_VS_CONFIRMED_DOCUMENT_EVIDENCE_MIXED**=`YES`
- **EVIDENCE**=`Single inference asks form + object_classification + registry category_code + contextual object priors + document_research_priority/confirmation_required without document text. Prompt MODE A/B and examples mix purchase mapping with object-prior prediction.`
