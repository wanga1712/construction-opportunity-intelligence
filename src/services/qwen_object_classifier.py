"""Qwen-backed escalation for procurement MODE / OBJECT (unresolved only).

WIP=MASS-CANONICAL-OBJECT-LAYER-RUN-V1, sections 3, 5, 6, 7.

This module is the *only* place a model is asked about a procurement.  It is
called strictly after the deterministic layers:

    Stage A   procurement mode   -> only when the deterministic mode gate
                                    (stored scope authority + dwelling rules +
                                    the pre-research scope gate) left UNKNOWN.
    Stage B   canonical object   -> only for MODE=OBJECT rows the deterministic
                                    object classifier left unresolved.

The object prompt is the frozen, proven object-classification contract (built
from ``expert_object_taxonomy``; no second enum).  The mode prompt is new but
frozen for this run.  Nothing is tuned while the run is live.

Hard rules
----------
1. ``temperature=0``, ``seed=42``, ``format=json``, model ``qwen2.5:7b`` -- the
   base model only; the failed LoRA adapter is never used.
2. Model output is canonical *only* after ``expert_object_taxonomy`` validation.
   An invalid / non-canonical / unparsable answer is reported as invalid; it is
   never coerced into a canonical code.
3. Every result keeps the raw model text separately from the canonical result.
4. ``classify_*`` never raises on a bad answer: transport errors surface as
   ``error`` so the caller can retry instead of persisting a wrong row.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from src.services import expert_object_taxonomy as OT
from src.services import product_ontology as PO

MODEL_NAME = "qwen2.5:7b"
MODEL_TEMPERATURE = 0
MODEL_SEED = 42
QWEN_CLASSIFIER_VERSION = "qwen_object_v1"

MODE_NUM_CTX = 2048
MODE_NUM_PREDICT = 160
OBJECT_NUM_CTX = 6144
OBJECT_NUM_PREDICT = 400
REQUEST_TIMEOUT = 900

MODE_SOURCE_QWEN = PO.PROCUREMENT_MODE_VALUES  # DIRECT / OBJECT / SERVICE_NO_OBJECT / AMBIGUOUS

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)

# --- taxonomy-derived prompt material (never a parallel enum) ---------------
def _sector_lines() -> str:
    rows = []
    for sector in OT.OBJECT_SECTOR_VALUES:
        types = OT.types_of_sector(sector)
        if types:
            rows.append(f"{sector}: {', '.join(types)}")
    return "\n".join(rows)


def _subtype_lines() -> str:
    rows = []
    for object_type, pairs in OT.OBJECT_SUBTYPES_BY_TYPE.items():
        codes = [code for code, _label in pairs]
        if codes:
            rows.append(f"{object_type}: {', '.join(codes)}")
    return "\n".join(rows)


def _context_codes() -> str:
    return ", ".join(code for code, _label in OT.OBJECT_CONTEXT_TERMS)


def _application_codes() -> str:
    return ", ".join(code for code, _label in OT.APPLICATION_AREA_TERMS)


MODE_PROMPT_HEAD = """ЗАДАЧА: определить ФОРМУ ЗАКУПКИ (procurement_mode) по канонической таксономии.
Детерминированные правила не смогли определить форму — реши сам.

РОВНО ОДНО значение procurement_mode:
- DIRECT: закупка ГОТОВОГО товара/продукции (поставка, приобретение, покупка) без работ по созданию или ремонту объекта.
- OBJECT: закупка работ/услуг, у которых есть физический ОБЪЕКТ (дорога, мост, тоннель, здание, сеть, территория, сооружение), в который встраиваются продукты.
- SERVICE_NO_OBJECT: чистая услуга без объекта (уборка, охрана, связь, страхование, обучение, аренда, обслуживание оборудования).
- AMBIGUOUS: недостаточно данных, либо смешанная форма (проектирование, изыскания, оборудование с монтажом).

ПРАВИЛА:
- Товар для объекта (ноутбук для школы) НЕ делает объект школой и НЕ делает форму OBJECT.
- Готовый товар (мебель, техника, материалы) -> DIRECT.
- Строительство / реконструкция / капитальный или текущий ремонт / благоустройство / монтаж объекта -> OBJECT.
- confidence — ЦЕЛОЕ число 0..100 (например 23, 67, 91). reason — до 200 символов.

ЗАКУПКА:
CRM_ID: {cid}
TITLE: {title}
OKPD: {okpd} — {okpd_name}

Ответ — СТРОГО один JSON:
{{"procurement_mode":"DIRECT|OBJECT|SERVICE_NO_OBJECT|AMBIGUOUS","confidence":0,"reason":"..."}}"""

OBJECT_PROMPT_HEAD = """ЗАДАЧА: определить ОБЪЕКТ закупки по КАНОНИЧЕСКОЙ таксономии. Выбор иерархический.

ПРОЦЕСС (СТРОГО ПО ШАГАМ):
ШАГ 1. Выбери OBJECT_SECTOR — ровно одно значение из списка секторов.
ШАГ 2. Выбери OBJECT_TYPE — ровно одно значение ТОЛЬКО из типов выбранного сектора.
        Тип обязан принадлежать выбранному сектору (HOTEL при RESIDENTIAL невозможен).
ШАГ 3. Выбери OBJECT_SUBTYPE — только из подтипов выбранного типа. Если подтипов нет -> "NONE".

ПРАВИЛА:
- FORM (форма закупки) уже известна как OBJECT. НЕ переопределяй её.
- object_sector / object_type / object_subtype: ТОЛЬКО значения из списков ниже. Свободный текст запрещён.
- object_context / application_area: ТОЛЬКО значения из соответствующих списков; массивы, могут быть пустыми.
- Не определяй объект по месту поставки товара (товар для школы НЕ делает объект школой).
- confidence — ЦЕЛОЕ число от 0 до 100 (примеры: 23, 67, 91). reason — до 200 символов.
- object_applicable="YES" если объект однозначно определяется; "UNKNOWN" если данных мало.

OBJECT_SECTOR (ровно один): {sectors}

OBJECT_TYPE (только из типов выбранного сектора):
{sector_types}

OBJECT_SUBTYPE (только для этих типов; иначе "NONE"):
{subtypes}

OBJECT_CONTEXT (массив, может быть пустым; только отсюда): {contexts}
APPLICATION_AREA (массив, может быть пустым; только отсюда): {applications}

ЗАКУПКА:
CRM_ID: {cid}
TITLE: {title}
OKPD: {okpd} — {okpd_name}
PROCUREMENT_MODE: OBJECT

Ответ — СТРОГО один JSON:
{{"object_applicable":"YES|UNKNOWN","object_sector":"...","object_type":"...","object_subtype":"...","object_context":[],"application_area":[],"confidence":0,"reason":"..."}}"""


def build_mode_prompt(crm_id: Any, title: Any, okpd_code: Any, okpd_name: Any) -> str:
    return MODE_PROMPT_HEAD.format(
        cid=crm_id, title=str(title or ""), okpd=str(okpd_code or "-"), okpd_name=str(okpd_name or "-")
    )


def build_object_prompt(crm_id: Any, title: Any, okpd_code: Any, okpd_name: Any) -> str:
    return OBJECT_PROMPT_HEAD.format(
        sectors=", ".join(OT.OBJECT_SECTOR_VALUES),
        sector_types=_sector_lines(),
        subtypes=_subtype_lines(),
        contexts=_context_codes(),
        applications=_application_codes(),
        cid=crm_id,
        title=str(title or ""),
        okpd=str(okpd_code or "-"),
        okpd_name=str(okpd_name or "-"),
    )


# --- transport --------------------------------------------------------------
def _default_call(prompt: str, *, num_ctx: int, num_predict: int) -> dict[str, Any]:
    import os

    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    body = json.dumps(
        {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": MODEL_TEMPERATURE,
                "seed": MODEL_SEED,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


CallFn = Callable[..., dict[str, Any]]


def _parse_json(text: Any) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    for candidate in (raw, *_JSON_BLOCK.findall(raw)):
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _as_int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return -1


def _as_code(value: Any) -> str | None:
    code = str(value or "").strip()
    if not code or code.upper() in ("NONE", "N/A", "NA", "NULL", "-", "NO"):
        return None
    return code.upper()


def _first_code(value: Any, allowed: Iterable[str]) -> str | None:
    # Codes may be mixed-case upstream (e.g. OBJECT_CONTEXT/APPLICATION_AREA
    # terms are lowercase, sector codes are uppercase); compare
    # case-insensitively and return the canonical allowed code.
    canonical = {str(code).strip().upper(): code for code in allowed}
    values = value if isinstance(value, (list, tuple)) else [value]
    for item in values:
        code = _as_code(item)
        if code and code in canonical:
            return canonical[code]
    return None


# --- results ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ModelModeResult:
    mode: str | None
    raw: str = ""
    reason: str = ""
    confidence: int = -1
    invalid: bool = False
    error: str | None = None
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None and not self.invalid and self.mode in PO.PROCUREMENT_MODE_VALUES


@dataclass(frozen=True, slots=True)
class ModelObjectResult:
    status: str
    sector: str | None = None
    object_type: str | None = None
    object_subtype: str | None = None
    object_context: str | None = None
    application_area: str | None = None
    raw: str = ""
    reason: str = ""
    confidence: int = -1
    invalid: bool = False
    error: str | None = None
    elapsed: float = 0.0
    matched_terms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.invalid


def classify_mode_via_model(
    title: Any,
    okpd_code: Any = None,
    okpd_name: Any = None,
    *,
    crm_id: Any = None,
    call: CallFn | None = None,
) -> ModelModeResult:
    """Ask the model for a canonical PROCUREMENT_MODE (Stage A escalation)."""
    fn = call or _default_call
    prompt = build_mode_prompt(crm_id, title, okpd_code, okpd_name)
    started = time.time()
    try:
        response = fn(prompt, num_ctx=MODE_NUM_CTX, num_predict=MODE_NUM_PREDICT)
    except Exception as exc:  # transport: caller retries, nothing is persisted
        return ModelModeResult(mode=None, error=repr(exc)[:300], elapsed=time.time() - started)
    raw = str(response.get("response", "") or "")
    parsed = _parse_json(raw)
    if parsed is None:
        return ModelModeResult(
            mode=None, raw=raw, invalid=True, reason="UNPARSABLE_JSON", elapsed=time.time() - started
        )
    mode = _as_code(parsed.get("procurement_mode"))
    if mode not in PO.PROCUREMENT_MODE_VALUES:
        return ModelModeResult(
            mode=None,
            raw=raw,
            invalid=True,
            reason=f"NON_CANONICAL_MODE:{parsed.get('procurement_mode')!r}",
            confidence=_as_int(parsed.get("confidence")),
            elapsed=time.time() - started,
        )
    return ModelModeResult(
        mode=mode,
        raw=raw,
        reason=str(parsed.get("reason") or "")[:200],
        confidence=_as_int(parsed.get("confidence")),
        elapsed=time.time() - started,
    )


def classify_object_via_model(
    title: Any,
    okpd_code: Any = None,
    okpd_name: Any = None,
    *,
    crm_id: Any = None,
    call: CallFn | None = None,
) -> ModelObjectResult:
    """Ask the model for canonical OBJECT axes (Stage B escalation).

    Returns ``OBJECT_UNCERTAIN`` for a well-formed "no/uncertain object" answer
    and ``MODEL_INVALID`` for a non-canonical or unparsable one.
    """
    from src.services.object_classification import (
        STATUS_MODEL_INVALID,
        STATUS_OBJECT_UNCERTAIN,
    )

    fn = call or _default_call
    prompt = build_object_prompt(crm_id, title, okpd_code, okpd_name)
    started = time.time()
    try:
        response = fn(prompt, num_ctx=OBJECT_NUM_CTX, num_predict=OBJECT_NUM_PREDICT)
    except Exception as exc:
        return ModelObjectResult(
            status=STATUS_MODEL_INVALID, error=repr(exc)[:300], elapsed=time.time() - started
        )
    raw = str(response.get("response", "") or "")
    parsed = _parse_json(raw)
    if parsed is None:
        return ModelObjectResult(
            status=STATUS_MODEL_INVALID, raw=raw, invalid=True,
            reason="UNPARSABLE_JSON", elapsed=time.time() - started,
        )

    confidence = _as_int(parsed.get("confidence"))
    reason = str(parsed.get("reason") or "")[:200]
    applicable = _as_code(parsed.get("object_applicable"))
    sector = _as_code(parsed.get("object_sector"))
    object_type = _as_code(parsed.get("object_type"))
    subtype = _as_code(parsed.get("object_subtype"))
    context = _first_code(parsed.get("object_context"), (c for c, _ in OT.OBJECT_CONTEXT_TERMS))
    area = _first_code(parsed.get("application_area"), (c for c, _ in OT.APPLICATION_AREA_TERMS))

    if applicable != "YES":
        return ModelObjectResult(
            status=STATUS_OBJECT_UNCERTAIN, raw=raw, reason=reason or "MODEL_NO_OBJECT",
            confidence=confidence, elapsed=time.time() - started,
        )
    if not OT.is_canonical_object_type(object_type, sector):
        return ModelObjectResult(
            status=STATUS_MODEL_INVALID, raw=raw, invalid=True,
            reason=f"NON_CANONICAL_OBJECT:{sector}/{object_type}", confidence=confidence,
            elapsed=time.time() - started,
        )
    if subtype and not OT.is_canonical_object_subtype(subtype, object_type):
        subtype = None
    from src.services.object_classification import STATUS_RESOLVED_MODEL

    return ModelObjectResult(
        status=STATUS_RESOLVED_MODEL,
        sector=OT.sector_of_object_type(object_type),
        object_type=object_type,
        object_subtype=subtype,
        object_context=context,
        application_area=area,
        raw=raw,
        reason=reason,
        confidence=confidence,
        elapsed=time.time() - started,
        matched_terms=tuple(t for t in (object_type, subtype, context, area) if t),
    )


def classifier_stats() -> dict[str, Any]:
    return {
        "model": MODEL_NAME,
        "classifier_version": QWEN_CLASSIFIER_VERSION,
        "temperature": MODEL_TEMPERATURE,
        "seed": MODEL_SEED,
        "mode_num_ctx": MODE_NUM_CTX,
        "object_num_ctx": OBJECT_NUM_CTX,
        "canonical_modes": list(PO.PROCUREMENT_MODE_VALUES),
        "sectors": list(OT.OBJECT_SECTOR_VALUES),
    }