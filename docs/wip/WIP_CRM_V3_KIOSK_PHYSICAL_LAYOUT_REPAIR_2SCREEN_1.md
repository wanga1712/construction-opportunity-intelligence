# WIP=CRM-V3-KIOSK-PHYSICAL-LAYOUT-REPAIR-2SCREEN-1

## Result

PASS. Replaced the rotating three-screen layout with two manually selected screens, fixed normal-flow grid layout, externalized the runtime HTML, and removed the hard-coded Firefox size. Business logic, collector semantics, database, and CRM were not changed.

## Source and deployment

- Branch: `feat/crm-v3-kiosk-multi-screen-command-center-1`
- Start HEAD: `c3c7ee647dbdddf3dfcc2f0cc81fbc5365a655e3`
- Physical kiosk: `/usr/local/bin/s13_dashboard3.py`, `/usr/local/bin/s13_kiosk_main.html`, `/usr/local/bin/s13_kiosk_start.sh`
- Backup: `/opt/CRM_Streamlit/backups/s13_kiosk_physical_layout_final_20261117_161147`
- X display: HDMI-0, 1920x1080+0+0; root 1920x1080
- Firefox: x=0, y=0, 1920x1080; inner viewport 1920x1080; DPR 1
- Browser title audit: `DIR ltr/ltr/ltr/ltr/ltr`, pipeline `01234`, document 1920x1080, outside 0

## Acceptance

- Exactly two screens: OPERATIONS and RESOURCES; no auto-rotation or critical screen override.
- Keyboard `1` and `2` manually select the screens. Operations and Resources each remained selected for 60 seconds.
- Physical pipeline displayed in order: ????????? ? ???????????? ????? ? ????????? ? ???????????? ? ??????.
- Physical Resources view displayed all 8 CPU cores, temperatures, CPU limits, GPU temperature/VRAM/power limits, RAM, disks, and cooling availability.
- Chromium computed-layout checks passed at 1920x1080, 1366x768, and 1280x720 for both screens: document dimensions fit; all marked groups stayed in viewport; no scroll.
- Python compile, JavaScript syntax, shell syntax, production import, `/`, `/tech`, and `/api/metrics` smoke checks passed. API response was 200 in 0.373 seconds. Runtime today received count was 38.
- Production services `s13-dashboard3.service` and `s13-kiosk.service` are active. No CRM restart or DB mutation.

## Artifacts

- [Operations physical screenshot](../../reports/s13_kiosk_physical_layout_operations.png)
- [Resources physical screenshot](../../reports/s13_kiosk_physical_layout_resources.png)

## Files

`deploy/s13_dashboard3.py`, `deploy/s13_kiosk_main.html`, `deploy/s13_kiosk_start.sh`, `tests/test_s13_kiosk_physical_layout.py`, and the two screenshots. The legacy three-screen test was replaced.
