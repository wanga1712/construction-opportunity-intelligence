# S13 production document workers - runtime authority

WIP: `S13-DOC-WORKER-RUNTIME-AUTHORITY-AND-AWARDED-FIX-1`
Host: S13 (`sergey-System-Product-Name`) ? date 2026-10-05

## Active production units (5)

| Unit | WORKER_ID | Scope / lanes | Backend | Queue |
|--|--|--|--|--|
| tender-docs-daemon-open.service | 13 | crm_active_hot,open_active,awarded_follow_up | S13_V4 | document_intelligence.document_processing_queue |
| tender-docs-daemon-open-2.service | 15 | crm_active_hot,open_active | S13_V4 | document_intelligence.document_processing_queue |
| tender-docs-daemon-awarded.service | 14 | awarded_recent,historical_awarded | S13_V4 | document_intelligence.document_processing_queue |
| tender-docs-daemon-awarded-2.service | 17 | flex (open/CRM, fallback awarded) | S13_V4 | document_intelligence.document_processing_queue |
| tender-docs-daemon-computers.service | 18 | open_active (computers OKPD) | S13_V4 | document_intelligence.document_processing_queue |

## Disabled / legacy (intentionally not deployed)

| Unit | Reason |
|--|--|
| tender-docs-daemon.service | duplicate of `-open` (same historical WORKER_ID=13) |
| tender-docs-daemon-open-3.service | redundant open-lane worker |
| tender-docs-daemon-computers-2.service | redundant computers worker |

Legacy unit files/templates stay in Git for history but must not be enabled on S13.

## CPU resource model (runtime authority)

- No per-worker CPUQuota. All workers share `crm-background-compute.slice`:
  `CPUQuota=500%`, `AllowedCPUs=2-7`, `CPUWeight=50`, `IOWeight=50`.
- CRM keeps priority: `crm-streamlit` CPUWeight=800, Nice=-10, MemorySwapMax=0;
  CPUs 0-1 are reserved for CRM/PostgreSQL/OS (background and user.slice are on 2-7).
- Host-wide CPU frequency ceiling `cpu-powerlimit.service` (no_turbo + 3.2 GHz) is
  deployed from the CRM deploy set (see `docs/reports/cpu_thermal_cap/`).

## Awarded defect and fix

Root cause: `tender-docs-daemon-awarded.service.d/zz-s13v4-backend.conf` was missing,
so the effective environment had **no** `PROCESSING_BACKEND=S13_V4`,
`MODEL_QUEUE_PRIORITY_ENABLED=1` or `S13_DOCUMENT_DB_*`. The worker fell back to the
legacy `tender_monitor` queue and failed with
`relation "document_processing_queue" does not exist`.

Fix: added the same `zz-s13v4-backend.conf` (and `30-mincifry-ca.conf`) drop-in that the
four working workers already use, so awarded resolves to
S13 local `document_intelligence.document_processing_queue` with `PROCESSING_BACKEND=S13_V4`.

## Deploy

```sh
rsync deploy/systemd/ /etc/systemd/system/   # review before running
systemctl daemon-reload
systemctl restart tender-docs-daemon-awarded.service
```
