"""Evaluate the STAGE 1 routing adapter (accuracy + real procurement samples).

Modes (S13):
  metrics:  /home/sergey/crm-training/venv/bin/python training/object_routing_v1/evaluate.py metrics \
                --adapter /home/sergey/crm-training/adapters/qwen2.5-7b-routing-v1 \
                --data-dir /home/sergey/crm-training/data
  samples:  ... evaluate.py samples --adapter ... --samples /home/sergey/crm-training/data/samples.jsonl
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys

import torch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))  # repo root (training/<wip>/ -> repo)
from routing_labels import LABELS, parse_labels  # noqa: E402
import bnb_sm75_patch  # noqa: E402,F401  (must precede model construction)

DEFAULT_MODEL_DIR = "/home/sergey/crm-training/models/qwen2.5-7b-instruct"


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build(model_dir, adapter):
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    tokenizer = AutoTokenizer.from_pretrained(adapter or model_dir, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    dtype_kw = {"dtype": torch.float16} if "dtype" in set(
        inspect.signature(AutoModelForCausalLM.from_pretrained).parameters
    ) else {"torch_dtype": torch.float16}
    base = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0}, low_cpu_mem_usage=True, **dtype_kw
    )
    if adapter:
        model = PeftModel.from_pretrained(base, adapter)
    else:
        model = base
    model.eval()
    return tokenizer, model


def prompts(tokenizer, rows):
    return [
        tokenizer.apply_chat_template(row["messages"][:-1], tokenize=False, add_generation_prompt=True)
        for row in rows
    ]


def generate(tokenizer, model, texts, batch_size=2, max_new_tokens=48, max_len=512):
    outputs = []
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        enc = tokenizer(
            chunk, return_tensors="pt", padding=True, truncation=True, max_length=max_len
        ).to(model.device)
        with torch.no_grad():
            gen = model.generate(
                **enc,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                num_beams=1,
                pad_token_id=tokenizer.pad_token_id,
            )
        for i in range(len(chunk)):
            new_tokens = gen[i][enc["input_ids"].shape[1] :]
            outputs.append(tokenizer.decode(new_tokens, skip_special_tokens=True))
        print("generated %d/%d" % (min(start + batch_size, len(texts)), len(texts)), flush=True)
    return outputs


def cmd_metrics(args):
    rows = load_jsonl(os.path.join(args.data_dir, "test.jsonl"))
    tokenizer, model = build(args.model_dir, args.adapter)
    texts = prompts(tokenizer, rows)
    raw = generate(tokenizer, model, texts, batch_size=args.batch_size)
    per_label_hit = {name: 0 for name in LABELS}
    per_label_total = 0
    exact = 0
    unparsed = 0
    for row, text in zip(rows, raw):
        pred = parse_labels(text)
        if pred is None:
            unparsed += 1
            continue
        per_label_total += 1
        if all(pred[name] == row["labels"][name] for name in LABELS):
            exact += 1
        for name in LABELS:
            if pred[name] == row["labels"][name]:
                per_label_hit[name] += 1
    total = len(rows)
    report = {
        "test_rows": total,
        "parsed": per_label_total,
        "unparsed": unparsed,
        "exact_match": exact / total if total else 0.0,
        "accuracy": {name: (per_label_hit[name] / total if total else 0.0) for name in LABELS},
    }
    print("METRICS " + json.dumps(report, ensure_ascii=False), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    return 0


def cmd_samples(args):
    rows = load_jsonl(args.samples)
    tokenizer, model = build(args.model_dir, args.adapter)
    texts = prompts(tokenizer, rows)
    raw = generate(tokenizer, model, texts, batch_size=args.batch_size)
    out = []
    for row, text in zip(rows, raw):
        pred = parse_labels(text)
        out.append(
            {
                "crm_id": row.get("crm_id"),
                "title": row.get("title"),
                "group": row.get("group"),
                "expected": row["labels"],
                "model": pred,
                "raw": text.strip()[:120],
                "ok": bool(pred is not None and all(pred[n] == row["labels"][n] for n in LABELS)),
            }
        )
    print("SAMPLES " + json.dumps(out, ensure_ascii=False), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
    acc = {name: (sum(1 for r in out if r["model"] and r["model"][name] == r["expected"][name]) / len(out) if out else 0.0) for name in LABELS}
    print("SAMPLE_ACCURACY " + json.dumps(acc, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["metrics", "samples"])
    ap.add_argument("--adapter")  # omit for base-model baseline
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--data-dir", default="/home/sergey/crm-training/data")
    ap.add_argument("--samples")
    ap.add_argument("--out")
    ap.add_argument("--batch-size", type=int, default=2)
    args = ap.parse_args()
    if args.mode == "metrics":
        return cmd_metrics(args)
    return cmd_samples(args)


if __name__ == "__main__":
    raise SystemExit(main())