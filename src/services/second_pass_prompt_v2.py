"""Second Pass V2 prompt builder (MEDAL SEMANTICS V2).

The prompt asks Qwen for CANONICAL CATEGORY RELEVANCE only. It never asks for a
commercial medal, and the procurement price (NMCK) is deliberately not rendered
into the prompt at all, so price can never influence relevance:

    CATEGORY RELEVANCE -> MEDAL
    PRICE / DEADLINE / URGENCY -> RANKING

Part of ANALYTICS-V2-MEDAL-SEMANTICS-V2-REBUILD-1 (PHASE 6.4).
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.services.medal_semantics_v2 import (
    CANONICAL_CATEGORY_CODES,
    MEDAL_SEMANTICS_VERSION,
    PRODUCTION_MODEL,
    PRODUCTION_PROMPT_VERSION,
)

#: Re-exported for callers that used to read these from second_pass_service.
SECOND_PASS_MODEL = PRODUCTION_MODEL
SECOND_PASS_PROMPT_VERSION = PRODUCTION_PROMPT_VERSION

_RELEVANCE_RULES = """### УРОВНИ РЕЛЕВАНТНОСТИ (поле relevance_level):
- "STRONG": документы прямо и однозначно описывают предмет закупки материалами/работами этой категории (есть конкретные позиции, объёмы, применение).
- "MODERATE": категория подтверждена явно, но занимает второстепенную или частичную долю закупки.
- "WEAK": категория упоминается косвенно, единично или неоднозначно.
- "NONE": коммерческой релевантности категории нет либо она исключена по смыслу."""

_SEMANTIC_BANS = """### СЕМАНТИЧЕСКИЕ ЗАПРЕТЫ (ложные срабатывания):
- flooring НЕ ставится за земляные работы, обратную засыпку, засыпку котлованов/траншей (это не полы).
- waterproofing НЕ ставится за теплоизоляцию, минераловатные маты, изоляцию трубопровода без гидроизоляционных материалов.
- lighting НЕ ставится за одно слово "опора" без светильников и осветительного оборудования.
- "грунтовка"/"грунтовочный" сами по себе НЕ являются гидроизоляцией.
- благоустройство, озеленение, соцтовары, питание, уборка, чистое проектирование без материалов — обычно NONE."""


def build_second_pass_prompt(
    proc_meta: Dict[str, Any],
    doc_stats: Dict[str, Any],
    snippets: List[Dict[str, Any]],
) -> str:
    """Build the strict semantics-v2 prompt for Qwen.

    ``proc_meta`` may contain ``initial_price``; it is intentionally ignored.
    """
    evidence_lines = []
    for i, s in enumerate(snippets, 1):
        evidence_lines.append(
            f"{i}. [{s.get('category_code', 'other_unmapped')}] "
            f"Doc: \"{s.get('document_name', 'Unknown_doc')}\" ({s.get('location', 'text')}) | "
            f"Term: \"{s.get('matched_term', '')}\" -> {s.get('text', '')}"
        )
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "NO_DOCUMENT_EVIDENCE_FOUND"
    cat_list_str = ", ".join(CANONICAL_CATEGORY_CODES)

    return f"""Ты — аналитик коммерческих закупок строительного сектора. Твоя задача: по ФАКТИЧЕСКОМУ СОДЕРЖИМОМУ ДОКУМЕНТОВ (evidence chunks) определить, есть ли в закупке реальная коммерческая релевантность каноническим товарным категориям, и насколько она сильна.

### ЖЁСТКИЕ ПРАВИЛА:
1. Ты оцениваешь ТОЛЬКО релевантность категории. Ты НЕ выставляешь медали — это делает программный код.
2. ЦЕНА, НМЦК, бюджет и объём контракта НЕ являются признаком релевантности. Дорогая непрофильная закупка остаётся непрофильной.
3. ОКПД2 не является доказательством релевантности: категорию определяет содержание документов, а не код.
4. Любой уровень кроме "NONE" ОБЯЗАН опираться на конкретную цитату из evidence chunks с указанием документа.
5. Если подтверждающих фрагментов нет — relevance_level = "NONE".

### ДАННЫЕ ЗАКУПКИ:
- ID: {proc_meta.get('id')}
- Номер: {proc_meta.get('contract_number')}
- Название: {proc_meta.get('auction_name')}
- Заказчик: {proc_meta.get('customer')}
- ОКПД2: {proc_meta.get('okpd_code')}
- Закон: {proc_meta.get('fz')}
- Всего документов: {doc_stats.get('document_count')}, обработано: {doc_stats.get('processed_document_count')}, находок: {doc_stats.get('evidence_count')}

### ИЗВЛЕЧЕННЫЕ ИЗ ДОКУМЕНТОВ ФРАГМЕНТЫ (EVIDENCE CHUNKS):
{evidence_block}

### СПИСОК ДОПУСТИМЫХ КАНОНИЧЕСКИХ КАТЕГОРИЙ:
{cat_list_str}

{_RELEVANCE_RULES}

{_SEMANTIC_BANS}

### FOUND FACTS (только конкретные товары/материалы):
- Заполняй `found_facts` ТОЛЬКО для конкретных товаров/материалов, прямо присутствующих в тексте evidence chunks.
- `product_name_normalized` ОБЯЗАН быть реальным наименованием товара/материала (не абстрактная категория, не заголовок).
- `source_quote` ОБЯЗАН быть точной цитатой из evidence chunk.
- Если evidence содержит только общие услуги или регламенты — оставь `found_facts: []`.

### ВЫХОДНОЙ ФОРМАТ (СТРОГО JSON):
Ответь ТОЛЬКО валидным JSON следующей структуры:
{{
  "object_classification": {{
    "object_family": "SOCIAL|COMMERCIAL|DIRECT_SUPPLY|OTHER",
    "object_type": "<тип объекта>",
    "object_subtype": "<подтип>",
    "work_stage": "<стадия работ>"
  }},
  "category_evaluations": [
    {{
      "category_code": "<канонический код категории из списка>",
      "relevance_level": "STRONG|MODERATE|WEAK|NONE",
      "reason": "<обоснование по категории>",
      "findings": ["<конкретная позиция, подтверждающая категорию>"],
      "evidence_refs": [
        {{"document_name": "<имя файла>", "matched_term": "<термин>", "location": "<page/row>", "quote": "<точная цитата>"}}
      ],
      "positive_signals": ["<семантический сигнал из документов>"],
      "negative_signals": ["<сигнал, снижающий релевантность>"],
      "commercial_exclusions": [{{"term": "<термин>", "exclusion_reason": "<причина>"}}]
    }}
  ],
  "commercial_exclusions": [
    {{"term": "<термин>", "category_code": "<код категории>", "exclusion_reason": "<причина исключения>"}}
  ],
  "found_facts": [
    {{
      "product_name_normalized": "<конкретное наименование>",
      "category_code": "<канонический код категории>",
      "support_type": "EXACT|NORMALIZED",
      "quantity": "<объем или null>",
      "unit": "<ед. изм. или null>",
      "unit_price": <цена или null>,
      "total_price": <сумма или null>,
      "document_name": "<файл источника>",
      "source_quote": "<точная цитата из evidence>"
    }}
  ],
  "model_reason": "<краткое объяснение (1-2 предложения)>",
  "model_name": "{SECOND_PASS_MODEL}",
  "prompt_version": "{SECOND_PASS_PROMPT_VERSION}",
  "semantics_version": {MEDAL_SEMANTICS_VERSION}
}}"""