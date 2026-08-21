#!/usr/bin/env python3
"""Phase 7.2 — T-lite direct Ollama smoke (no CRM integration, not calibration)."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

MODEL = os.environ.get(
    "T_LITE_MODEL_ID",
    "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M",
)
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

PROMPTS = [
    (
        "A_RU_INSTR",
        "Ответь одной короткой русской фразой: что значит «поставка моноблоков» в закупках?",
    ),
    (
        "B_JSON_ONLY",
        'Верни ТОЛЬКО JSON объект без markdown и без рассуждений: '
        '{"procurement_form":"SUPPLY","object_type":null,"note":"поверка счетчиков"}',
    ),
    (
        "C_PROCUREMENT",
        "Классифицируй предмет закупки одной фразой: ремонт автомобильной дороги.",
    ),
]


def _generate(prompt: str) -> tuple[str, float]:
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 128},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("response") or ""), time.perf_counter() - t0


def main() -> int:
    results = []
    json_ok = False
    for key, prompt in PROMPTS:
        text, sec = _generate(prompt)
        row = {"key": key, "seconds": round(sec, 3), "response": text[:500]}
        if key == "B_JSON_ONLY":
            try:
                cleaned = text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.strip("`")
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:].strip()
                parsed = json.loads(cleaned)
                row["json_parse_ok"] = isinstance(parsed, dict)
                json_ok = bool(row["json_parse_ok"])
            except Exception as exc:
                row["json_parse_ok"] = False
                row["json_error"] = str(exc)
                json_ok = False
            row["has_think_tag"] = "<think>" in text.lower() or "</think>" in text.lower()
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    out = {
        "T_LITE_MODEL_ID": MODEL,
        "T_LITE_SMOKE_RESPONSE": "PASS" if len(results) == 3 and all(r.get("response") for r in results) else "FAIL",
        "T_LITE_JSON_CAPABLE": "YES" if json_ok else "NO",
        "THINKING_MODE_USED": "NO",
        "results": results,
    }
    Path = __import__("pathlib").Path
    Path("/tmp/phase72_t_lite_smoke.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("SMOKE=" + json.dumps({k: out[k] for k in out if k != "results"}, ensure_ascii=False))
    return 0 if out["T_LITE_SMOKE_RESPONSE"] == "PASS" and out["T_LITE_JSON_CAPABLE"] == "YES" else 1


if __name__ == "__main__":
    raise SystemExit(main())
