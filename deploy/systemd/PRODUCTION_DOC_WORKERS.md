# S13 production document workers - runtime authority (band routing)

WIP: `S13-DOC-WORKER-BAND-ROUTING-1` ? Host S13 ? 2026-10-05

## Active production units (5)

| Unit | WORKER_ID | QUEUE_BANDS | CPUQuota |
|--|--|--|--|
| tender-docs-band-gold-1.service | 31 | GOLD | floating (pool) |
| tender-docs-band-gold-2.service | 32 | GOLD | floating (pool) |
| tender-docs-band-silver.service | 33 | SILVER | floating (pool) |
| tender-docs-band-bronze.service | 34 | BRONZE | floating (pool) |
| tender-docs-band-wood.service | 35 | WOOD,UNSCORED | 100% (fixed) |

Routing:
- primary = `research_prior_band` (`QUEUE_BANDS`);
- secondary ordering = `queue_lane` -> `priority_score` -> FIFO (`created_at`; the queue
  table has no deadline column, priority_score already encodes deadline urgency);
- source/awarded/computers specialization = OFF (no QUEUE_LANES / QUEUE_TABLE_SOURCES);
- all workers use `PROCESSING_BACKEND=S13_V4` -> `document_intelligence.document_processing_queue`.

## Disabled / legacy (not deployed)

tender-docs-daemon-open, -open-2, -awarded, -awarded-2, -computers (source-specialized),
plus base tender-docs-daemon, -open-3, -computers-2. Files kept for history.

## Deploy

```sh
cp deploy/systemd/tender-docs-band-*.service /etc/systemd/system/
cp -r deploy/systemd/tender-docs-band-*.service.d /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tender-docs-band-{gold-1,gold-2,silver,bronze,wood}.service
```
