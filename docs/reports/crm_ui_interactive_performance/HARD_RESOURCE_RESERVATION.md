# Hard Resource Reservation

WIP: `CRM-UI-INTERACTIVE-PERFORMANCE-AND-RESOURCE-GUARANTEE-1`

## Policy principle

```text
WEIGHT_ONLY_POLICY_SUFFICIENT=NO
INTERACTIVE_CPU_HEADROOM_HARD_RESERVED=YES
BACKGROUND_CAN_CONSUME_100_PERCENT_ALL_CPUS=NO
```

Reserve interactive logical CPUs for CRM / PostgreSQL / critical OS work. Background AI is **excluded** from those CPUs via cgroup v2 `AllowedCPUs=`.

## Topology-derived assignment

| | |
|--|--|
| CPU_COUNT | 8 |
| INTERACTIVE_RESERVED_CPUS | `0-1` (one physical core + SMT sibling) |
| BACKGROUND_ALLOWED_CPUS | `2-7` |

CRM and PostgreSQL are **not** pinned; they may use all CPUs including reserved ones. Background slice cannot schedule on `0-1`.

## systemd artifacts (Git)

| Path | Role |
|--|--|
| `deploy/systemd/crm-background-compute.slice` | AllowedCPUs=`2-7`, CPUQuota=`600%`, MemoryHigh=`22G`, MemorySwapMax=`8G`, CPUWeight/IOWeight=`50` |
| `deploy/systemd/crm-streamlit.service.d/20-hard-interactive.conf` | CPUWeight=`800`, MemoryMin=`384M`, MemoryLow=`768M`, MemorySwapMax=`0`, Nice=`-10`, OOMScoreAdjust=`-300` |
| `deploy/systemd/ollama.service.d/20-background-slice.conf` | Slice=`crm-background-compute.slice` |
| `deploy/systemd/crm-ai-assessment-runner.service.d/20-background-slice.conf` | same slice |
| `deploy/systemd/tender-docs-daemon-*.service.d/20-background-slice.conf` | same slice when units exist |
| `scripts/run_background_compute.sh` | one-off AI via `systemd-run --slice=crm-background-compute.slice` |

```text
ONE_OFF_AI_JOB_RESOURCE_POLICY=YES
BACKGROUND_CPU_QUOTA=600%
CRM_MEMORY_MIN=384M
CRM_MEMORY_LOW=768M
CRM_MEMORY_SWAP_MAX=0
```

Memory Min/Low sized from measured Streamlit RSS (~218–230 MiB) + headroom. SwapMax=0 keeps CRM pages resident (no global swap disable).

## Live unit state (after apply)

- `crm-streamlit`: MemorySwapMax=0, MemoryMin≈384M, MemoryLow≈768M, CPUWeight=800
- `ollama`: ControlGroup under `crm-background-compute.slice`; children `Cpus_allowed_list=2-7`
- Slice: AllowedCPUs=`2-7`, CPUQuota=`6s` (=600%)

Restarts: `crm-streamlit`, `ollama` (required to attach Slice). PostgreSQL / S7 **not** restarted.

## Memory / models

| Metric | Value |
|--|--|
| CRM_RSS_IDLE/NORMAL (sample) | ~218 MiB |
| CRM_RSS_PEAK (sample) | ~218–230 MiB |
| POSTGRES_RSS (checkpointer class) | ~100–150 MiB processes |
| CRM_SWAP_DURING_CONTENTION | **0** |
| SIMULTANEOUS_MODEL_MEMORY_PRESSURE | **NO** (single `qwen2.5:7b` loaded during acceptance load) |

GPU may remain AI-dedicated; host CPU/RAM starvation is what this policy prevents.
