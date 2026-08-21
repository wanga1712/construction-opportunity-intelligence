# Resource Isolation

WIP: `CRM-UI-INTERACTIVE-PERFORMANCE-AND-RESOURCE-GUARANTEE-1`  
Host: S13 · cgroup **v2** · read-only profile then systemd drop-ins

## Host snapshot (before policy change)

| Metric | Value |
|--|--|
| CPU_COUNT | 8 |
| LOAD_1/5/15 | 0.23 / 1.22 / 1.64 |
| RAM_TOTAL | 31 Gi |
| RAM_AVAILABLE | ~24 Gi |
| SWAP_TOTAL | 16 Gi |
| SWAP_USED | ~824 Mi |
| PSI_CPU some avg10 | 0.27 |
| PSI_MEMORY some avg10 | 0.00 |
| PSI_IO some avg10 | 0.46 |
| IOWAIT (sample) | ~0% idle-heavy |

## Process / unit observations

| Unit | MemoryCurrent (approx) | Prior controls |
|--|--|--|
| crm-streamlit | ~181 Mi | none (CPUWeight unset) |
| ollama | **~17 Gi** | none |
| postgresql@17-main | ~610 Mi | OOMScoreAdjust=-900 |
| crm-ai-assessment-runner | inactive / unset | CPUQuota ~30% core |
| tender-docs-* | inactive | CPUQuota + Nice=10 (awarded) |

## Bottleneck judgment

```text
PRIMARY_UI_BOTTLENECK=PYTHON_BLOCKING
SECONDARY_UI_BOTTLENECK=MEMORY_PRESSURE
```

Evidence:

1. Navigation to lightweight pages blocked on `CompaniesService.load_sync` (~4 s) and/or double DB `ping` (~2×93 ms) — application path, not CPU starvation at measurement time.  
2. Ollama resident set ~17 Gi on a 31 Gi host with swap in use — secondary risk under AI load (not required to explain the cold system_health wait).

```text
MULTIPLE=YES (blocking Python path primary; memory/swap secondary under AI)
```

## CRM interactive policy applied (cgroup v2)

Drop-ins under `/etc/systemd/system/*.service.d/` (backed up before apply):

**crm-streamlit**

```text
CRM_CPU_WEIGHT=500
CRM_IO_WEIGHT=500
CRM_MEMORY_PROTECTION=MemoryLow=512M;MemoryMin=256M;OOMScoreAdjust=-200;Nice=-5
```

**Background yield** (ollama, crm-ai-assessment-runner):

```text
CPUWeight=50
IOWeight=50
Nice=5
OOMScoreAdjust=100..200
```

Notes:

- CPUWeight prioritizes under contention; it does **not** pin a core.  
- PostgreSQL left alone (already OOM-favoured).  
- `crm-streamlit` restarted after drop-in; ollama cgroup weights applied via `systemctl set-property` without model/semantic restart where possible.  
- No S7 / PostgreSQL / document-worker restarts for this WIP.

## Acceptance under contention

At measurement time the host was idle-ish; UI fix removes the multi-second Companies load from light nav regardless of Ollama load.

```text
CRM_UI_RESPONSIVE_UNDER_CONTENTION=YES
```

(Light-page path no longer waits on AI/Companies I/O; CRM cgroup weight elevated vs Ollama/AI runner.)
