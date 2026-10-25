#!/bin/bash
# STAGE 1 object-routing LoRA fine-tune: unattended pipeline.
#
# WIP=ANALYTICS-V2-TRAINING-STAGE-1-OBJECT-ROUTING
# Triggered by crm-training-routing-v1.timer (on boot, and daily at 06:05).
#
#   1. wait until the GPU actually has enough free VRAM;
#   2. fine-tune qwen2.5:7b -> qwen2.5-7b-routing-v1 (LoRA; base weights frozen);
#   3. evaluate that adapter on the held-out test split and on the real samples.
#
# Every stage is skipped when its artefact already exists, so a repeated
# trigger never redoes finished work, and an interrupted run simply restarts.
set -uo pipefail

case "${1:-}" in
  ""    ) CHECK_ONLY=0 ;;
  --check ) CHECK_ONLY=1 ;;
  --help|-h)
      echo "usage: $(basename "$0") [--check]"
      echo "  (no args) run the STAGE 1 pipeline: train, then evaluate (idempotent)"
      echo "  --check   verify preconditions and GPU availability, then exit"
      exit 0 ;;
  * ) echo "unexpected argument: $1"; exit 2 ;;
esac

TRAIN_HOME=/home/sergey/crm-training
VENV="$TRAIN_HOME/venv/bin/python"
REPO=/opt/CRM_Streamlit
STAGE1="$REPO/training/object_routing_v1"
DATA="$TRAIN_HOME/data_run1"
SAMPLES="$TRAIN_HOME/data/samples.jsonl"
OUT="$TRAIN_HOME/adapters/qwen2.5-7b-routing-v1"
STATE="$TRAIN_HOME/state"
LOG="$TRAIN_HOME/logs/boot_training.log"

export HF_HOME="$TRAIN_HOME/hf"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

mkdir -p "$STATE" "$TRAIN_HOME/logs"
exec >> "$LOG" 2>&1

exec 9>"$STATE/training.lock"
if ! flock -n 9; then echo "ANOTHER_RUN_ACTIVE"; exit 0; fi

log() { echo "[$(date '+%F %H:%M:%S')] $*"; }
log "=== pipeline start (pid $$) ==="

missing=0
for path in "$VENV" "$STAGE1/train_lora.py" "$STAGE1/evaluate.py" \
            "$DATA/train.jsonl" "$DATA/test.jsonl" "$SAMPLES"; do
  if [ ! -e "$path" ]; then log "MISSING $path"; missing=1; fi
done
[ "$missing" = 0 ] || { log "PRECONDITION_FAILED"; exit 1; }

for attempt in $(seq 1 60); do
  free_mib=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
  case "$free_mib" in ''|*[!0-9]*) free_mib=0 ;; esac
  if [ "$free_mib" -ge 5200 ]; then
    log "gpu free=${free_mib}MiB attempt=$attempt"
    break
  fi
  log "waiting for gpu: free=${free_mib}MiB attempt=$attempt"
  sleep 30
done
if [ "$free_mib" -lt 5200 ]; then log "GPU_BUSY_ABORT free=${free_mib}MiB"; exit 1; fi

if [ "$CHECK_ONLY" = 1 ]; then log "CHECK_ONLY ok free=${free_mib}MiB"; exit 0; fi

if [ -f "$OUT/train_report.json" ] && grep -q '"smoke": false' "$OUT/train_report.json"; then
  log "TRAIN skip: adapter already trained"
else
  rm -rf "$OUT"
  log "TRAIN start"
  "$VENV" "$STAGE1/train_lora.py" \
    --data-dir "$DATA" --out "$OUT" \
    --epochs 1 --grad-accum 4 --lr 2e-4 --eval-steps 0 --grad-ckpt on
  train_rc=$?
  log "TRAIN exit=$train_rc"
  [ "$train_rc" = 0 ] || { log "TRAIN_FAILED"; exit 1; }
fi

if [ -f "$STATE/metrics.json" ]; then
  log "METRICS skip: already evaluated"
else
  log "METRICS start"
  "$VENV" "$STAGE1/evaluate.py" metrics --adapter "$OUT" --data-dir "$DATA" \
    --out "$STATE/metrics.json"
  log "METRICS exit=$?"
fi

if [ -f "$STATE/samples_result.json" ]; then
  log "SAMPLES skip: already evaluated"
else
  log "SAMPLES start"
  "$VENV" "$STAGE1/evaluate.py" samples --adapter "$OUT" --samples "$SAMPLES" \
    --out "$STATE/samples_result.json"
  log "SAMPLES exit=$?"
fi

if [ -f "$STATE/metrics.json" ] && [ -f "$STATE/samples_result.json" ]; then
  touch "$STATE/PIPELINE_DONE"
  log "=== pipeline done ==="
  exit 0
fi
log "=== pipeline incomplete ==="
exit 1