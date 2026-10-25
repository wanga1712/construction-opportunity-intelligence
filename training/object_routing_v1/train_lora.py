"""REAL LoRA/QLoRA fine-tune of Qwen2.5-7B-Instruct for TRAINING STAGE 1.

Learns exactly three independent procurement-type flags (SOCIAL / PROJECT /
DIRECT_SUPPLY).  It does NOT learn GOLD/SILVER/BRONZE/WOOD, commercial category
or priority.  The base model is frozen; only the LoRA adapter is trained.

6 GB VRAM constraints that shaped this file:
  * full 4-bit Qwen2.5-7B weights already take ~5.2 GiB, so LoRA is attention-only
    (q/k/v/o, r=8) and the tied fp16 embedding is left untouched;
  * ``peft.prepare_model_for_kbit_training`` is NOT used (it upcasts the whole
    embedding to fp32 = extra 2 GiB); only the tiny RMSNorm weights go to fp32;
  * the LM head is evaluated only on the answer span (``logits_to_keep``), so
    cross-entropy never materialises 448 x 152k logits.

Usage (S13):
    /home/sergey/crm-training/venv/bin/python training/object_routing_v1/train_lora.py \
        --data-dir /home/sergey/crm-training/data \
        --out /home/sergey/crm-training/adapters/qwen2.5-7b-routing-v1
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import platform
import sys
import time

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bnb_sm75_patch  # noqa: E402,F401  (must precede model construction)

DEFAULT_MODEL_DIR = "/home/sergey/crm-training/models/qwen2.5-7b-instruct"
ATTENTION_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]
ALL_MODULES = ATTENTION_MODULES + ["gate_proj", "up_proj", "down_proj"]
RUN_LEDGER = "/home/sergey/crm-training/runs.jsonl"


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _as_ids(out):
    if hasattr(out, "input_ids"):
        out = out.input_ids
    if isinstance(out, torch.Tensor):
        out = out.tolist()
    if out and isinstance(out[0], list):
        out = out[0]
    return list(out)


def encode_supervised(tokenizer, messages, max_len):
    """Return ids + the answer span (logit positions and target token ids)."""
    full = _as_ids(tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False))
    prefix = _as_ids(
        tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
    )
    if full[: len(prefix)] != prefix:
        prefix = full[: min(len(full), len(prefix))]
    start = len(prefix)
    end = min(len(full), max_len)
    if start >= end:
        return None
    return {
        "input_ids": full[:end],
        "keep_idx": list(range(start - 1, end - 1)),
        "targets": full[start:end],
    }


class SupervisedDataset(torch.utils.data.Dataset):
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]


def make_collator(pad_token_id):
    def collate(features):
        width = max(len(f["input_ids"]) for f in features)
        width_k = max(len(f["keep_idx"]) for f in features)
        input_ids, attention, keep, targets = [], [], [], []
        for feature in features:
            pad = width - len(feature["input_ids"])
            pad_k = width_k - len(feature["keep_idx"])
            input_ids.append(list(feature["input_ids"]) + [pad_token_id] * pad)
            attention.append([1] * len(feature["input_ids"]) + [0] * pad)
            keep.append(list(feature["keep_idx"]) + [0] * pad_k)
            targets.append(list(feature["targets"]) + [-100] * pad_k)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
            "keep_idx": torch.tensor(keep, dtype=torch.long),
            "targets": torch.tensor(targets, dtype=torch.long),
        }

    return collate


def half_dtype_kwargs():
    """`dtype` replaced `torch_dtype` in transformers 5; keep the fp16 load explicit.

    Without this the non-quantised tied embedding/lm_head stay bf16 while the
    quantization compute dtype is fp16, and every lm_head call pays a 1 GiB
    weight cast that OOMs a 6 GB card.
    """
    from transformers import AutoModelForCausalLM

    sig = set(inspect.signature(AutoModelForCausalLM.from_pretrained).parameters)
    return {"dtype": torch.float16} if "dtype" in sig else {"torch_dtype": torch.float16}


def prepare_kbit_model(model, grad_ckpt=True):
    """Minimal 4-bit prep that fits a 6 GB card (see module docstring)."""
    model.config.use_cache = False
    # The bitsandbytes loader unties word embeddings (config -> False) and keeps a
    # second bf16 copy of the 152k x 3584 matrix. Re-tying frees ~1.0 GiB.
    embed = model.get_input_embeddings()
    head = model.get_output_embeddings()
    if embed is not None and head is not None and head.weight.data_ptr() != embed.weight.data_ptr():
        if tuple(head.weight.shape) == tuple(embed.weight.shape):
            model.config.tie_word_embeddings = True
            stale = head.weight
            head.weight = embed.weight
            del stale
            if hasattr(model, "tie_weights"):
                model.tie_weights()
            print(
                "prepare_kbit_model: re-tied word embeddings, alloc=%.1f MiB"
                % (torch.cuda.memory_allocated() / 2**20),
                flush=True,
            )
    cast = 0
    for name, param in model.named_parameters():
        if param.dtype in (torch.float16, torch.bfloat16) and "norm" in name.lower():
            param.data = param.data.to(torch.float32)
            cast += 1
    print("prepare_kbit_model: norm params cast to fp32 =", cast, flush=True)
    if grad_ckpt:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    torch.cuda.empty_cache()
    return model


def make_trainer_class():
    from transformers import Trainer

    class SpanLossTrainer(Trainer):
        """Cross-entropy computed only on the answer span (``logits_to_keep``)."""

        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            keep_idx = inputs.pop("keep_idx")
            targets = inputs.pop("targets")
            outputs = model(**inputs, logits_to_keep=keep_idx)
            logits = outputs.logits
            flat = logits.reshape(-1, logits.shape[-1]).float()
            target = targets.reshape(-1)
            valid = int((target != -100).sum())
            loss = F.cross_entropy(flat, target, ignore_index=-100, reduction="sum")
            loss = loss / max(valid, 1)
            return (loss, outputs) if return_outputs else loss

    return SpanLossTrainer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--data-dir", default="/home/sergey/crm-training/data")
    ap.add_argument("--out", default="/home/sergey/crm-training/adapters/qwen2.5-7b-routing-v1")
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lora-r", type=int, default=8)
    ap.add_argument("--lora-alpha", type=int, default=16)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-steps", type=int, default=-1, help="smoke override")
    ap.add_argument("--save-steps", type=int, default=0, help="0 = per epoch")
    ap.add_argument("--proj", choices=["attention", "all"], default="attention")
    ap.add_argument("--grad-ckpt", choices=["on", "off"], default="on")
    ap.add_argument("--eval-steps", type=int, default=0, help="0 = no mid-run eval")
    ap.add_argument("--eval-rows", type=int, default=0, help="0 = every validation row")
    args = ap.parse_args()
    args.grad_ckpt = args.grad_ckpt == "on"

    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(args.seed)
    if not torch.cuda.is_available():
        print("FATAL: CUDA is required for this training run", file=sys.stderr)
        return 2

    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token or "<|endoftext|>"
    tokenizer.padding_side = "right"

    train_rows = load_jsonl(os.path.join(args.data_dir, "train.jsonl"))
    val_rows = load_jsonl(os.path.join(args.data_dir, "validation.jsonl"))

    train_enc, val_enc, skipped = [], [], 0
    for row in train_rows:
        encoded = encode_supervised(tokenizer, row["messages"], args.max_len)
        if encoded is None:
            skipped += 1
        else:
            train_enc.append(encoded)
    for row in val_rows:
        encoded = encode_supervised(tokenizer, row["messages"], args.max_len)
        if encoded is not None:
            val_enc.append(encoded)
    if args.eval_rows and len(val_enc) > args.eval_rows:
        val_enc = val_enc[: args.eval_rows]

    lengths = sorted(len(r["input_ids"]) for r in train_enc)
    spans = sorted(len(r["targets"]) for r in train_enc)
    print(
        "tokenized train=%d val=%d skipped=%d len(min/med/p95/max)=%d/%d/%d/%d span(max)=%d"
        % (
            len(train_enc),
            len(val_enc),
            skipped,
            lengths[0] if lengths else 0,
            lengths[len(lengths) // 2] if lengths else 0,
            lengths[int(len(lengths) * 0.95)] if lengths else 0,
            lengths[-1] if lengths else 0,
            spans[-1] if spans else 0,
        ),
        flush=True,
    )

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_dir,
        quantization_config=bnb,
        device_map={"": 0},
        low_cpu_mem_usage=True,
        **half_dtype_kwargs(),
    )
    print("bnb_sm75_patch PATCHED=%s" % bnb_sm75_patch.PATCHED, flush=True)
    model = prepare_kbit_model(model, args.grad_ckpt)

    lora = LoraConfig(
        task_type="CAUSAL_LM",
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        bias="none",
        target_modules=ATTENTION_MODULES if args.proj == "attention" else ALL_MODULES,
    )
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print("lora trainable=%d (%.3f%% of %d)" % (trainable, 100.0 * trainable / total, total), flush=True)

    arg_kwargs = dict(
        output_dir=os.path.join(args.out, "checkpoints"),
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_steps=20,
        max_grad_norm=0.3,
        optim="paged_adamw_8bit",
        fp16=True,
        gradient_checkpointing=args.grad_ckpt,
        logging_steps=5,
        eval_strategy="steps" if args.eval_steps > 0 else "no",
        save_strategy="steps" if args.save_steps else "epoch",
        save_total_limit=2,
        report_to=[],
        dataloader_num_workers=0,
        remove_unused_columns=False,
        seed=args.seed,
    )
    if args.save_steps:
        arg_kwargs["save_steps"] = args.save_steps
    if args.eval_steps > 0:
        arg_kwargs["eval_steps"] = args.eval_steps
    if args.max_steps and args.max_steps > 0:
        arg_kwargs["max_steps"] = args.max_steps
        arg_kwargs["num_train_epochs"] = 1.0
        arg_kwargs["save_strategy"] = "no"
    trainer_sig = set(inspect.signature(TrainingArguments.__init__).parameters)
    arg_kwargs = {k: v for k, v in arg_kwargs.items() if k in trainer_sig or k == "output_dir"}
    training_args = TrainingArguments(**arg_kwargs)

    trainer_cls = make_trainer_class()
    trainer_kwargs = dict(
        model=model,
        args=training_args,
        data_collator=make_collator(tokenizer.pad_token_id),
        train_dataset=SupervisedDataset(train_enc),
    )
    if args.eval_steps > 0:
        trainer_kwargs["eval_dataset"] = SupervisedDataset(val_enc)
    if "processing_class" in set(inspect.signature(trainer_cls.__init__).parameters):
        trainer_kwargs["processing_class"] = tokenizer
    trainer = trainer_cls(**trainer_kwargs)

    started = time.time()
    result = trainer.train()
    runtime = time.time() - started

    os.makedirs(args.out, exist_ok=True)
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)

    metrics = dict(result.metrics)
    report = {
        "stage": "object_routing_stage1",
        "base_model_dir": args.model_dir,
        "base_model": "qwen2.5:7b",
        "derived_model": "qwen2.5-7b-routing-v1",
        "adapter_dir": args.out,
        "prompt_version": train_rows[0].get("prompt_version") if train_rows else None,
        "train_rows": len(train_enc),
        "validation_rows": len(val_enc),
        "eval_loss": metrics.get("eval_loss"),
        "train_loss": metrics.get("train_loss"),
        "global_steps": metrics.get("global_step"),
        "runtime_sec": round(runtime, 1),
        "epochs": args.epochs,
        "lr": args.lr,
        "grad_accum": args.grad_accum,
        "max_len": args.max_len,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "lora_proj": args.proj,
        "trainable_params": trainable,
        "total_params": total,
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "python": platform.python_version(),
        "grad_ckpt": args.grad_ckpt,
        "bnb_sm75_patched": bool(bnb_sm75_patch.PATCHED),
        "smoke": bool(args.max_steps and args.max_steps > 0),
        "peak_vram_mib": round(torch.cuda.max_memory_allocated() / 2**20, 1),
    }
    with open(os.path.join(args.out, "train_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    if not report["smoke"]:
        with open(RUN_LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    print("REPORT " + json.dumps(report, ensure_ascii=False), flush=True)
    print("TRAINING_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())