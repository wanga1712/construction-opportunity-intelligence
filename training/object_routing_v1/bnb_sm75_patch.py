"""Force bitsandbytes' native 4-bit GEMM kernel on sm75 (GTX 1660 SUPER).

bitsandbytes' per-architecture heuristic routes most shapes to
``_dequant_linear_fallback`` on sm75, which materialises a full fp16 copy of every
weight and keeps it alive for the backward pass (~11 GiB for Qwen2.5-7B).  That
makes QLoRA training impossible on a 6 GB card even though the model itself only
uses ~4.3 GiB.  The native 4-bit kernel reads the packed uint8 weights directly,
so it neither allocates nor retains those copies.

Import this module *before* building the model.
"""
from __future__ import annotations

import torch

PATCHED = False


def _always_custom(device_index, dtype, M, N, K):
    # fp32 has no 4-bit MMA/SIMT kernel; keep bitsandbytes' own choice there.
    if dtype == torch.float32:
        return M < 8
    return True


def apply() -> bool:
    global PATCHED
    try:
        from bitsandbytes.backends.cuda import ops as bnb_ops
    except Exception:
        return False
    bnb_ops._gemm_4bit_use_custom_cuda = _always_custom
    if hasattr(bnb_ops, "_gemm_4bit_use_custom_fn"):
        bnb_ops._gemm_4bit_use_custom_fn = _always_custom
    PATCHED = True
    return True


apply()