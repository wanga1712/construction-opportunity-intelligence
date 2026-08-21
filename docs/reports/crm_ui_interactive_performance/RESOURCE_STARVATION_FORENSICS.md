# Resource Starvation Forensics

WIP: `CRM-UI-INTERACTIVE-PERFORMANCE-AND-RESOURCE-GUARANTEE-1` (reopened)  
Status before hard reservation: `PREVIOUS_WIP_PASS=REVOKED` / `RESOURCE_STARVATION_NOT_SOLVED`

## Verdict

```text
FREEZE_REPRODUCED=YES (operator live acceptance under active compute; weights-only era)
WEIGHT_ONLY_POLICY_SUFFICIENT=NO
SERVER_SCHEDULER_STARVATION=YES (click wait before rerun while host compute saturates CPUs)
UI_CODE_BLOCKING_AGAIN=NO (light-nav app fixes retained; CompaniesService still skipped)
```

## Host topology

| Item | Value |
|--|--|
| CPU_COUNT | 8 logical (4 cores × 2 SMT) |
| CPU model | Intel Core i7-2600K |
| NUMA | 1 node, CPUs 0–7 |
| RAM | ~31 Gi |
| SWAP | 16 Gi file |
| cgroup | v2 |

## Reproduction under real compute

Heavy work observed during reopen / contention:

| PROCESS_ROLE | SYSTEMD_UNIT_OR_SCOPE | CGROUP_PATH | notes |
|--|--|--|--|
| Ollama llama-server | `ollama.service` | `…/crm-background-compute.slice/ollama.service` (after fix) | Was saturating multiple CPUs with **no AllowedCPUs** under weights-only policy; RSS multi‑GiB |
| AI assessment drain | `crm-ai-assessment-runner.service` | background slice (after fix) | Timer-triggered; Nice=5 |
| Manual / bake-off Python | historically SSH / user session | **user.slice / session** risk | T-lite bake-off was paused; one-off jobs must use controlled wrapper |

```text
UNCONTROLLED_HEAVY_PROCESSES_FOUND=YES (historical risk: SSH/manual AI jobs outside unit)
HEAVY_COMPUTE_OUTSIDE_CONTROLLED_CGROUP=0 (post-policy: burn + ollama load launched via systemd-run into crm-background-compute.slice)
```

## Sample peaks (post-policy contention window)

CPU burn pinned to AllowedCPUs `2–7` + Ollama generate loop:

| Metric | Peak / min |
|--|--|
| LOAD_1 | ~1.1 (sample; burn workers ~95% on CPUs 2–7) |
| CPU_RUN_QUEUE_PEAK | 6–9 |
| MEM_AVAILABLE_MIN | ~28 Gi (sample window) |
| SWAP_USED_PEAK | ~845 Mi (host; CRM VmSwap=0) |
| PSI_CPU_SOME_PEAK avg10 | ~0.77 |
| PSI_MEMORY_SOME_PEAK | ~0.0 |
| PSI_IO_SOME_PEAK | ~0.95 |

CRM process under contention: PSR on reserved interactive CPUs (`0–1` observed), Nice=`-10`, **VmSwap=0**.

Ollama llama-server: `Cpus_allowed_list=2-7`.

## Click latency locus

Instrument: optional `CRM_UI_NAV_TRACE` in `app_bootstrap` (body timings). Synthetic HTTP under contention:

```text
CLICK_WAIT_BEFORE_SERVER_MS = (operator / websocket; HTTP smoke ≠ full click)
SERVER_RERUN / PAGE_RENDER (light path) = app fixes keep body path free of CompaniesService
HTTP smoke under contention: p50≈7 ms, p95≈9 ms, max≈12 ms
```

Interpretation: with hard CPU exclusion, Streamlit retains headroom on reserved CPUs. Full sidebar click confirmation remains **operator** acceptance.

## Root cause (weights-only era)

CPUWeight is relative priority only. Background AI could still consume **all** CPUs; interactive CRM could wait for scheduler even when page render code is fast.

```text
WEIGHT_ONLY_POLICY_SUFFICIENT=NO
```
