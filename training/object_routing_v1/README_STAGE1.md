# TRAINING STAGE 1 — object routing

`WIP=ANALYTICS-V2-TRAINING-STAGE-1-OBJECT-ROUTING`

Real LoRA/QLoRA fine-tune of `qwen2.5:7b` (base weights frozen) producing the adapter
`qwen2.5-7b-routing-v1`.

## What the model learns

Exactly three independent flags. It does **not** learn medals
(GOLD/SILVER/BRONZE/WOOD), commercial categories or `priority_score`.

| flag | meaning |
|---|---|
| `SOCIAL` | the object or the buyer is a social-purpose facility (school, clinic, culture, sport, university) |
| `PROJECT` | the contract contains construction / repair / design / installation works |
| `DIRECT_SUPPLY` | the subject of the contract is supply of goods |

Reference semantics: school construction → `S=P=yes, DS=no`; computers to a school →
`S=yes, P=no, DS=yes`; office capital repair → `S=no, P=yes, DS=no`; printer cartridges →
`S=no, P=no, DS=yes`.

Labels come from the project's existing deterministic routing authority
(`routing_labels.derive_labels` → `ProcurementScopeClassifierV1` plus the object taxonomy).
Old model medals are never used as ground truth. Price is deliberately not an input:
it can never create relevance.

## Unattended run on S13

```
crm-training-routing-v1.timer   (OnCalendar=06:05 daily, Persistent=true)
        -> crm-training-routing-v1.service   (Type=oneshot, User=sergey, TimeoutStartSec=infinity)
        -> training/object_routing_v1/run_stage1_training.sh
```

`run_stage1_training.sh` is idempotent and skips finished stages:

1. waits until the GPU actually has >= 5.2 GiB free (`nvidia-smi`), up to 30 min;
2. trains only when `adapters/qwen2.5-7b-routing-v1/train_report.json` is missing
   or contains `"smoke": true`;
3. runs `evaluate.py metrics` only when `state/metrics.json` is missing;
4. runs `evaluate.py samples` only when `state/samples_result.json` is missing;
5. writes `state/PIPELINE_DONE` once every artefact exists.

A single global `flock` (`state/training.lock`) guarantees that a second trigger —
for example the 06:05 timer while a boot-time run is still active — cannot start a
second training.

Log: `/home/sergey/crm-training/logs/boot_training.log`

## Commands

```bash
# verify preconditions + GPU only (no training, ~seconds)
/opt/CRM_Streamlit/training/object_routing_v1/run_stage1_training.sh --check

# run the pipeline now (blocks until finished)
sudo systemctl start crm-training-routing-v1.service

# watch it
tail -f /home/sergey/crm-training/logs/boot_training.log

# rebuild the dataset (only if the label contract changes)
bash /opt/CRM_Streamlit/training/object_routing_v1/build_dataset.sh   # see below
```

Dataset builder (needs `CRM_DB_*` from `/opt/CRM_Streamlit/.env`):

```bash
cd /opt/CRM_Streamlit && ./.venv313/bin/python training/object_routing_v1/build_dataset.py \
    --out /home/sergey/crm-training/data --from 2026-04-01 --to 2026-10-01 \
    --per-bucket 130 --val-frac 0.15 --test-frac 0.15
```

## Results

| artefact | path |
|---|---|
| adapter | `/home/sergey/crm-training/adapters/qwen2.5-7b-routing-v1` |
| training report | `.../qwen2.5-7b-routing-v1/train_report.json` |
| run ledger (all real runs) | `/home/sergey/crm-training/runs.jsonl` |
| test-split metrics | `/home/sergey/crm-training/state/metrics.json` |
| 33 real-procurement samples | `/home/sergey/crm-training/state/samples_result.json` |

## Environment constraints (measured, not assumed)

* GTX 1660 SUPER, 6 GB (sm75), 31 GB RAM; usable VRAM ≈ 5.6 GiB.
* `bnb_sm75_patch` is **load-bearing**: without it bitsandbytes routes 4-bit GEMMs to
  `_dequant_linear_fallback` on sm75 (~11 GiB of retained fp16 weights). It must be
  imported before the model is constructed — `train_lora.py` and `evaluate.py` do that.
* Gradient checkpointing cannot be disabled: activations OOM the card (`CUDA out of memory`
  at `sdpa_attention_forward`). Measured cost of the compact prompt: ≈ 20 s per row,
  ≈ 82 s per optimizer step at `--grad-accum 4`.
* `HF_HOME=/home/sergey/crm-training/hf` and
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` are required.
* Training venv (`/home/sergey/crm-training/venv`, py3.12, torch 2.5.1+cu121) is separate
  from the production venv `.venv313`, which has no torch.