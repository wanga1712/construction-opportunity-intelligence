# WIP=CRM-V3-KIOSK-ONE-SCREEN-ONLY-1

## Result: PASS

The physical S13 kiosk now has one persistent main screen. It contains the current task, compact resource summary, one ordered today pipeline, actionable attention, latest events, and commercial OPEN/AWARDED totals and medals. Screen navigation and every secondary screen were removed. Data API and business logic are unchanged.

## Runtime acceptance

- Source branch: `feat/crm-v3-kiosk-multi-screen-command-center-1`
- Start HEAD: `db2e10f2b284d579b4bb9cd0c2ca10e27e6d056c`
- Physical display remained HDMI-0 at 1920x1080+0+0.
- Firefox remained x=0, y=0, 1920x1080; inner viewport 1920x1080; DPR 1.
- Root geometry before and after: 1920x1080. Firefox was refreshed in place; kiosk/X was not restarted.
- Browser title audit: `DOC 1920x1080 | OUTSIDE 0 | PIPE 01234`.
- Live HTML has exactly one `#screen-main`, no `data-screen`, navigation, selectors, or hidden screens.
- Physical snapshot contains current AI procurement and elapsed time, CPU load/temperature/frequency, all 8 cores, CPU cap/turbo, GPU load/temperature/power limit, VRAM, RAM, all five pipeline stages in correct order, three attention items, three events, commercial total, OPEN/AWARDED totals and medals.
- Chromium bounds/contracts passed at 1920x1080, 1366x768, and 1280x720. Focused suite: 8 passed. JavaScript syntax check passed. `/api/metrics` polling remains 3 seconds.
- `s13-dashboard3.service` and `s13-kiosk.service` are active. No CRM restart, collector change, database mutation, or business logic change.

## Artifact

- [Physical one-screen kiosk screenshot](../../reports/s13_kiosk_one_screen.png)

## Files

`deploy/s13_kiosk_main.html`, `tests/test_s13_kiosk_physical_layout.py`, this report, and the physical screenshot. Dashboard Python and kiosk startup script were not changed.
