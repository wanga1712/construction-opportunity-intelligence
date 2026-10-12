# S13 CPU power cap and CRM resource reservation

WIP: `S13-CPU-POWER-CAP-AND-CRM-RESOURCE-RESERVATION-1`
Host: S13 (`sergey-System-Product-Name`) · Ubuntu · kernel 7.0.0-28-generic · cgroup v2
Reason: operator report `SERVER 13 CPU 97.5% / 73 °C warning`.

## Host facts

| Item | Value |
|--|--|
| CPU | Intel Core i7-2600K, 8 logical (4c/8t), 1.6–3.8 GHz |
| Governor | `schedutil` via `intel_cpufreq` (intel_pstate passive) |
| CPU package limit | RAPL present, but `enabled=0` and writes fail (`I/O error`) — firmware-locked |
| RAM | 31 GiB total, ~17 GiB available, swap ~67 MiB used, memory PSI 0.00 |
| GPU cap | `/etc/systemd/system/nvidia-powerlimit.service` → `nvidia-smi -pl 90` (90 W of 135 W max) |

## Root cause

CPU saturation was not the CRM. Only three background units were inside
`crm-background-compute.slice`; the rest of the AI/OCR workers ran in
`system.slice` with effectively unlimited aggregate CPU:

```
tender-docs-daemon (CPUQuota=700%), -open-2, -open-3, -awarded-2,
-computers, -computers-2, crm-v3-autonomous-worker, crm-v3-factual-feeder,
crm-v3-learning-observer, ...  -> system.slice, allowed on CPUs 0-7
```

Combined the per-unit quotas allowed ~16+ cores of load on an 8-thread host
(observed load 22–25, CPU PSI `some avg10` ≈ 56%). The existing
`AllowedCPUs=2-7` reservation for CRM was therefore not enforced.

## Changes applied (persisted in `deploy/systemd/`)

1. `crm-background-compute.slice`: `CPUQuota` 600% → **400%**, `AllowedCPUs=2-7`
   (background can never take more than 4 of the 6 background threads).
2. `cpu-powerlimit.service` (new): CPU analogue of `nvidia-powerlimit.service`.
   RAPL is locked by firmware, so the ceiling is `no_turbo=1`,
   `max_perf_pct=84`, `scaling_max_freq=3200000` (~3.19 GHz, down from 3.8 GHz).
3. `user.slice.d/20-crm-ui-reserve.conf` (new): interactive/manual shell jobs
   are kept on CPUs 2-7 with `CPUQuota=200%`, so they cannot steal the CRM cores.
4. `20-background-slice.conf` drop-ins for every AI/document background unit
   (27 units) → all heavy background work is now confined to
   `crm-background-compute.slice` (CPUs 2-7).

Result: CPUs **0-1 stay reserved** for `crm-streamlit` + `postgresql@17-main` + OS.

## Phase 2 — 5 workers with a floating pool (operator request)

8 document workers were too many for this host. Worker inventory before:

| Unit | WORKER_ID | Lanes |
|--|--|--|
| `tender-docs-daemon` (base) | 13 (duplicate of `-open`) | all |
| `-open` / `-open-2` / `-open-3` | 13 / 15 / 16 | `crm_active_hot,open_active` |
| `-awarded` / `-awarded-2` | 14 / 17 | awarded lanes / flex (all lanes) |
| `-computers` / `-computers-2` | 18 / 19 | `open_active` (computers OKPD) |

Applied:

- **Keep 5** workers covering all lanes: `-open`, `-open-2`, `-awarded`,
  `-awarded-2` (flex/floating), `-computers`.
- **Disabled + stopped 3** redundant workers: `tender-docs-daemon` (base,
  duplicate `WORKER_ID=13`), `tender-docs-daemon-open-3`,
  `tender-docs-daemon-computers-2`.
- **Floating resources**: per-worker `CPUQuota` cleared (`30-floating-cpu.conf`),
  so the 5 workers share one pool by `CPUWeight=50` instead of rigid quotas
  (previously 700/450/350/200/200…%). The pool ceiling is the slice
  `CPUQuota=500%` (4-6 CPU effective range) on CPUs 2-7.

After Phase 2: load ~12, CPU temp 63 °C, CRM HTTP 200 (155 ms), GPU 80/90 W.
CPU non-idle can still read high because the floating pool is deliberately
filled when CRM is idle; the operator can lower the ceiling to 400% if the
monitoring CPU warning must disappear.

## Verification (S13, 2026-10-05)

| Metric | Before | After |
|--|--|--|
| CPU non-idle (10 s sample) | ~97% (peak) | ~77% (idle ~23%) |
| Load 1 min | 22–25 | ~9.7 |
| CPU temp (Package id 0) | 72–73 °C | 65–67 °C |
| CPU PSI `some avg10` | ~56% | ~5–24% |
| Background slice | units in `system.slice` | all in slice, throttled at 400% |
| CRM HTTP `127.0.0.1:8504` | 200 | 200 (43–156 ms) |
| GPU | 57–60 W / 90 W, 57 °C | 56 W / 90 W, 57 °C |

CRM properties unchanged: `CPUWeight=800`, `Nice=-10`, `MemoryLow=768M`,
`MemorySwapMax=0`, no `AllowedCPUs` restriction (it may use 0-1 plus any idle
background threads).

## Notes / deviations

- RAPL package power capping is **not possible** on this host (firmware lock);
  the frequency ceiling is the available CPU power analogue.
- Pre-existing failures, unrelated to this change:
  `crm-second-pass-worker.service` (stop timeout 2026-09-28) and
  `crm-procurement-sync.service` (`UndefinedColumn: c.updated_at`, 2026-10-05 09:28).
- RAM is not a CPU lever: memory PSI is 0.00 and swap is unused, yet CPU is
  bound by OCR (`tesseract`) and LLM inference. Free RAM buys caching/residency,
  not extra cores.
- Revert: restore `/root/cpu-cap-backup-20261005_093809/` and
  `systemctl disable --now cpu-powerlimit.service`, then remove slice drop-ins.
