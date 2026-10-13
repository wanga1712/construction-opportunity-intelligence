# Disabled document workers (2026-10-13)

These units were running configuration that the application logic does **not**
execute. They are disabled **and** renamed to `*.service.disabled` on S13, so the
units are no longer loadable (`systemctl is-enabled` → `not-found`).

## Why

| Unit | Reason |
|---|---|
| `tender-docs-daemon-computers` | env declares `OKPD_ONLY_PREFIXES=26.20` / `OKPD_MATCH_PREFIX=1`, but the S13 claim path (`S13V2QueueRepository.claim_batch`) filters by lane + admission + generation only — the OKPD filter is never applied. The worker therefore just duplicated the `open_active` lane. |
| `tender-docs-daemon-computers-2` | Same OKPD-only config as above (worker 19), same dead filter. |
| `tender-docs-daemon-awarded-2` | `QUEUE_LANES_FLEX=1` picks lanes opportunistically (falls back to `crm_active_hot` / `open_active`), i.e. it can claim work outside its declared `*_awarded` table sources. |

Still enabled (canonical): `tender-docs-daemon-open`, `-open-2`, `-open-3`,
`tender-docs-daemon-awarded`.

## Re-enable

```bash
sudo mv /etc/systemd/system/<unit>.service.disabled /etc/systemd/system/<unit>.service
sudo systemctl daemon-reload
sudo systemctl enable --now <unit>
```

Only do this together with a fix that makes the worker's declared behaviour
actually effective (e.g. add the OKPD filter to the S13 claim path) — otherwise
the worker is a plain duplicate of the open workers again.
