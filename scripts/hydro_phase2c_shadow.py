"""Offline stratified Qwen shadow assessment for Hydro commercial entities."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import psycopg2.extras

from src.services.ai_client import configured_model, generate_json_with_meta
from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.hydro.commercial_hierarchy import (
    CommercialLayer,
    HydroObjectCommercialClass,
    build_qwen_shadow_prompt,
    build_qwen_shadow_payload,
    build_commercial_entities,
    shadow_input_hash,
    validate_shadow_result,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek/deepseek-chat"


def _generate_openrouter_json(prompt: str, *, timeout: int, num_predict: int) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": int(num_predict),
        "response_format": {"type": "json_object"},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"OpenRouter request failed: {type(exc).__name__}") from exc
    try:
        content = body["choices"][0]["message"]["content"]
        result = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("OpenRouter returned invalid JSON content") from exc
    return result, {"model": DEEPSEEK_MODEL, "provider": "openrouter"}


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
        model_name = DEEPSEEK_MODEL if args.backend == "openrouter" else (args.model or configured_model())
        if args.backend == "openrouter" and args.model and not args.model.startswith("deepseek/"):
            raise SystemExit("OpenRouter backend accepts only a deepseek/* model")

        def assess(entity: Any) -> dict[str, Any]:
            payload_hash = shadow_input_hash(build_qwen_shadow_payload(entity))
            try:
                if args.backend == "openrouter":
                    result, meta = _generate_openrouter_json(build_qwen_shadow_prompt(entity), timeout=args.timeout, num_predict=args.num_predict)
                else:
                    result, meta = generate_json_with_meta(build_qwen_shadow_prompt(entity), model=model_name, timeout=args.timeout, num_predict=args.num_predict)
                result = validate_shadow_result(result)
                return {"entity_key": entity.entity_key, "layer": entity.layer.value, "input_hash": payload_hash, "result": result, "model": meta.get("model") or model_name, "prompt_version": "hydro_commercial_interest_v1"}
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
