#!/usr/bin/env python3
"""SECTION_LEVEL_NORMALIZATION_V1 (Phase 4) — РУЧНОЙ model fallback для одного раздела.

Никогда не вызывается демоном. По умолчанию — dry-run (`DB_WRITES=0`): загружает материалы
раздела, спрашивает модель по жёсткой схеме, валидирует fail-closed и печатает, что было бы
записано. Только с явным `--apply` результат пишется ЧЕРЕЗ `structured_fact_repository`
(`save_extraction_run`), trust_state = `MANUAL_PROOF_QUARANTINE`.

    cd /opt/CRM_Streamlit && set -a && . ./.env; set +a
    .venv313/bin/python scripts/section_model_fallback_apply.py \
        --procurement-id 148391 --section-code '…'            # dry-run
    .venv313/bin/python scripts/section_model_fallback_apply.py \
        --procurement-id 148391 --section-code '…' --apply    # запись

`--self-test` прогоняет сборку ExtractionRun на синтетике с подставным ответом модели и
проверяет контракт (`validate_extraction_run`) без обращения к модели и без записи.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg2
import psycopg2.extras


def _conn():
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kwargs = dict(require_crm_db_connect_kwargs())
    kwargs["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    kwargs.setdefault("connect_timeout", 8)
    return psycopg2.connect(**kwargs)


def _build_run(contract, fallback, *, procurement_id, section_code, rows, text, model_name):
    """Собрать ExtractionRun строго по контракту (fail-closed проверяется отдельно)."""
    def _raw(number):
        """raw-значение должно дословно присутствовать в цитате («200», а не «200.0»)."""
        if number is None:
            return None
        value = float(number)
        return str(int(value)) if value.is_integer() else str(value)

    category = rows[0].get("category_code") or "unknown"
    detail_id = rows[0].get("detail_id")
    entities = []
    for child in fallback.get("children") or []:
        quote = child["source_quote"]
        unit = child.get("unit")
        qty = child.get("quantity")
        total = child.get("total_value")
        evidence = [contract.StructuredFieldEvidence("product_name", quote)]
        if qty is not None:
            evidence.append(contract.StructuredFieldEvidence("quantity", quote))
        if total is not None:
            evidence.append(contract.StructuredFieldEvidence("total_price", quote))
        entities.append(contract.StructuredEntity(
            product_name_raw=child["material_name"],
            product_name_normalized=child["material_name"],
            source_quote=quote,
            entity_type="PRODUCT",
            quantity_raw=_raw(qty),
            quantity_value=qty,
            quantity_unit_raw=unit,
            quantity_unit_normalized=unit,
            total_price_raw=_raw(total),
            total_price_value=total,
            confidence=0.5,
            field_evidence=evidence,
            section_code=section_code,
            section_name=fallback.get("section_name"),
            section_total_price_value=fallback.get("section_total_value"),
            section_total_price_raw=fallback.get("section_total_raw"),
            section_total_source=fallback.get("section_total_source"),
        ))
    run = contract.ExtractionRun(
        detail_id=detail_id,
        procurement_id=procurement_id,
        category_code=category,
        source_text_snapshot=text,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        document_name=(rows[0].get("document_name") or "section_model_fallback"),
        page_or_sheet=rows[0].get("page_or_sheet"),
        model_name=model_name,
        status="COMPLETED",
        raw_response=fallback,
        entities=entities,
    )
    return run


def _self_test() -> int:
    sys.path.insert(0, "/opt/tender_documents_research")
    sys.path.insert(0, "/opt/CRM_Streamlit")
    from tender_documents_research.document_processor import structured_fact_contract as contract
    import tender_documents_research.document_processor.section_model_fallback as fallback_mod

    text = ("Глава 12. Восстановление асфальтобетонного покрытия м2 100 500 50000\n"
            "Бордюр дорожный м 200 300 60000")
    payload = {
        "section_name": "Глава 12",
        "section_total_raw": "Бордюр дорожный м 200 300 60000",
        "section_total_value": 60000,
        "children": [{"material_name": "Бордюр дорожный", "quantity": 200, "unit": "м",
                      "total_value": 60000, "source_quote": "Бордюр дорожный м 200 300 60000"}],
    }
    valid = fallback_mod.validate_section_payload(payload, text)
    if not valid:
        print("SELF_TEST: payload not validated (unexpected)")
        return 1
    rows = [{"category_code": "composite_structures", "detail_id": None,
             "document_name": "self-test", "page_or_sheet": "S1"}]
    run = _build_run(contract, valid, procurement_id=0, section_code="S1::глава 12",
                     rows=rows, text=text, model_name="qwen2.5:7b")
    ok, errors = contract.validate_extraction_run(run)
    print("SELF_TEST: validate_extraction_run ->", ok, "| entities:", len(run.entities))
    if errors:
        for err in errors[:5]:
            print("   ", err)
    first = run.entities[0] if run.entities else None
    if first is not None:
        print("   section:", first.section_code, "|", first.section_name,
              "| total:", first.section_total_price_value, "| source:", first.section_total_source)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procurement-id", type=int, default=148391)
    ap.add_argument("--section-code")
    ap.add_argument("--max-rows", type=int, default=30)
    ap.add_argument("--apply", action="store_true", help="записать результат (по умолчанию dry-run)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    if not args.section_code:
        ap.error("--section-code is required (or use --self-test)")

    sys.path.insert(0, "/opt/tender_documents_research")
    sys.path.insert(0, "/opt/CRM_Streamlit")
    from tender_documents_research.document_processor import structured_fact_contract as contract
    import tender_documents_research.document_processor.section_model_fallback as fallback_mod
    from tender_documents_research.document_processor.structured_fact_repository import (
        save_extraction_run,
    )

    conn = _conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT se.category_code, se.page_or_sheet, se.source_quote, se.section_total_source,
                   se.section_total_price_value, se.section_code,
                   (SELECT min(id) FROM document_match_details d WHERE d.procurement_id = se.procurement_id) AS detail_id
              FROM structured_entities se
             WHERE se.procurement_id = %s AND se.section_code = %s
             ORDER BY se.total_price_value DESC NULLS LAST, se.id
             LIMIT %s
            """,
            (args.procurement_id, args.section_code, args.max_rows),
        )
        rows = cur.fetchall()
        if not rows:
            print("NO_ROWS for section", args.section_code)
            return 0
        rows = [dict(r, document_name=None) for r in rows]
        need = fallback_mod.section_needs_fallback(
            rows[0].get("section_total_price_value"), rows[0].get("section_total_source")
        )
        text = "\n".join(str(r.get("source_quote") or "") for r in rows if r.get("source_quote"))
        prepared = fallback_mod.prepare_section_text(text)
        print("section:", args.section_code, "| rows:", len(rows), "| fallback_needed:", need,
              "| apply:", bool(args.apply))
        if not need:
            print("SKIP: детерминированный контекст уже уверенный (SECTION_TOTAL/COMPUTED_SUM)")
            return 0

        result = fallback_mod.extract_sections_with_model(prepared)
        if not result:
            print("MODEL_RESULT: NO_VALID_PAYLOAD (fail-closed) — писать нечего")
            return 0
        run = _build_run(contract, result, procurement_id=args.procurement_id,
                         section_code=args.section_code, rows=rows, text=prepared,
                         model_name="qwen2.5:7b")
        ok, errors = contract.validate_extraction_run(run)
        print("contract_valid:", ok, "| entities:", len(run.entities),
              "| section_total:", result.get("section_total_value"),
              "| source:", result.get("section_total_source"))
        for err in errors[:5]:
            print("   ERR:", err)
        if not ok:
            print("DRY_RUN/APPLY ABORTED: контракт не прошёл (fail-closed)")
            return 1
        if not args.apply:
            print("DRY_RUN OK: DB_WRITES=0")
            return 0
        run_id = save_extraction_run(conn, run)
        conn.commit()
        print("APPLIED: structured_extraction_runs.id =", run_id, "| entities:", len(run.entities))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
