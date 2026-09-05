"""Offline stratified Qwen shadow assessment for Hydro commercial entities."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import psycopg2.extras

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.hydro.ai_providers import CommercialAssessmentInput, LocalQwenProvider, OpenRouterProvider
from src.services.hydro.commercial_hierarchy import (
    CommercialLayer,
    HydroObjectCommercialClass,
    build_qwen_shadow_prompt,
    build_qwen_shadow_payload,
    build_commercial_entities,
    shadow_input_hash,
)

def _rows(connection: Any) -> list[dict[str, Any]]:
    query = """
    SELECT DISTINCT ON (po.id) po.id AS object_id, po.source_object_id,
           po.cadastral_number, po.address, po.area_total, po.floors_underground,
           po.purpose, po.object_type, po.source_payload->>'name' AS name,
           po.source_payload->>'uk_id' AS source_company_id,
           po.source_payload->>'uk_ogrn' AS company_ogrn,
           e.management_company_id, mc.name AS company_name, mc.inn AS company_inn,
           e.object_potential, e.lead_readiness
    FROM parking_prefunnel_objects po
    LEFT JOIN crm_hydro_lead_objects lo ON lo.parking_object_id=po.id
    LEFT JOIN crm_hydro_lead_extensions e ON e.lead_id=lo.lead_id
    LEFT JOIN management_companies mc ON mc.id=e.management_company_id
    WHERE po.source_system='NSPD_PARKING'
    ORDER BY po.id, lo.is_primary DESC NULLS LAST, lo.lead_id
    """
    with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute(query)
        return list(cursor.fetchall())


def _sample(entities: tuple[Any, ...], per_stratum: int) -> list[Any]:
    groups: dict[str, list[Any]] = {"ZHILISHNIK": [], "OTHER_UK": [], "NO_UK_COMMERCIAL": [], "NO_UK_SPECIAL": []}
    special = {HydroObjectCommercialClass.STATE_PUBLIC, HydroObjectCommercialClass.SOCIAL, HydroObjectCommercialClass.CULTURAL, HydroObjectCommercialClass.SPORT, HydroObjectCommercialClass.TRANSPORT}
    for entity in entities:
        if entity.layer == CommercialLayer.ZHILISHNIK:
            groups["ZHILISHNIK"].append(entity)
        elif entity.layer == CommercialLayer.OTHER_UK:
            groups["OTHER_UK"].append(entity)
        elif entity.layer == CommercialLayer.NO_UK_KNOWN:
            cls = entity.object_class.commercial_class if entity.object_class else HydroObjectCommercialClass.UNKNOWN
            groups["NO_UK_SPECIAL" if cls in special else "NO_UK_COMMERCIAL"].append(entity)
    selected: list[Any] = []
    for values in groups.values():
        selected.extend(values[:per_stratum])
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="cache path outside the repository")
    parser.add_argument("--per-stratum", type=int, default=25)
    parser.add_argument("--model", default=None)
    parser.add_argument("--backend", choices=("openrouter", "ollama"), default="openrouter")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--num-predict", type=int, default=300)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--resume", default=None, help="existing external cache; retry only failed records")
    args = parser.parse_args()
    connection = psycopg2.connect(**require_crm_db_connect_kwargs())
    try:
        entities = build_commercial_entities(_rows(connection))
        selected = _sample(entities, max(1, args.per_stratum))
        records: list[dict[str, Any]] = []
        channels: dict[str, int] = {}
        if args.resume:
            try:
                previous = json.loads(Path(args.resume).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = {}
            records = [row for row in previous.get("records", []) if "result" in row]
            channels = dict(previous.get("channels", {}))
            completed_keys = {row.get("entity_key") for row in records}
            selected = [entity for entity in selected if entity.entity_key not in completed_keys]
        provider = OpenRouterProvider(args.model) if args.backend == "openrouter" else LocalQwenProvider(args.model or "qwen2.5:7b")
        model_name = provider.model

        def assess(entity: Any) -> dict[str, Any]:
            payload_hash = shadow_input_hash(build_qwen_shadow_payload(entity))
            try:
                assessment = provider.assess(CommercialAssessmentInput(entity.entity_key, payload_hash, build_qwen_shadow_prompt(entity)), timeout=args.timeout, max_tokens=args.num_predict)
                return {"entity_key": entity.entity_key, "layer": entity.layer.value, "input_hash": payload_hash, "result": assessment.result, "provider": assessment.provider, "model": assessment.model, "latency_sec": round(assessment.latency_sec, 3), "usage": assessment.usage, "prompt_version": "hydro_commercial_interest_v1"}
            except Exception as exc:
                return {"entity_key": entity.entity_key, "layer": entity.layer.value, "input_hash": payload_hash, "error_class": type(exc).__name__}

        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(selected)))) as pool:
            futures = [pool.submit(assess, entity) for entity in selected]
            for future in as_completed(futures):
                record = future.result()
                records.append(record)
                if "result" in record:
                    channel = record["result"]["recommended_channel"]
                    channels[channel] = channels.get(channel, 0) + 1
        records.sort(key=lambda row: row["entity_key"])
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"contract": "hydro_commercial_interest_v1", "model": model_name, "backend": args.backend, "sample_size": len(records), "channels": channels, "records": records}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        print(json.dumps({"sample_size": len(selected), "completed": sum("result" in r for r in records), "failed": sum("error_class" in r for r in records), "channels": channels}, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
