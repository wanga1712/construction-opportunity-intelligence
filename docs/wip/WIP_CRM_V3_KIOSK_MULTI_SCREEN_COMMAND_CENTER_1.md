# WIP=CRM-V3-KIOSK-MULTI-SCREEN-COMMAND-CENTER-1

Status: deployed and committed on the isolated kiosk branch; automated contracts pass, but
physical browser acceptance FAILS because the 1920x1080 S13 display still clips
and misplaces content on all three screens. Do not treat this WIP as accepted.

## Scope and safety

Only the kiosk entrypoint changed in production. Runtime HTML is embedded in
`deploy/s13_dashboard3.py`; `/tech` is served by the unchanged technical page.
No CRM application, collector, commercial logic, model logic, document pipeline,
routing logic or database was changed. API polling is 3 seconds; aggregate
caches retain their prior intervals. Responses send no-cache headers.

## Source and release

- Isolated branch starts at `c6d185f9e1890e8d9a79f9e281eeed01f5e5373f`.
- Initial live preimage SHA-256: `1abaeb9ce84f134069a6aac6f7b201d21093bc2724bcbb1178beaaacde260d60`.
- Final live/deploy SHA-256: `108a27fb92fbf57a1b04ce19c0971c8c78e4ae889fb3973f8e3b1e5b8a996f42`.
- Timestamped preimage backups and hash manifests are under `/opt/CRM_Streamlit/backups/s13_kiosk_multiscreen_20261117_*`.
- Runtime Python 3.12 compile, fresh import, `/`, `/api/metrics`, and `/tech` smoke checks passed. Dashboard and physical kiosk services are active. No CRM service was restarted.
- Deploy had several failed preflight/visual iterations; hash-verified automatic rollback restored each prior live file. Final deployment is the hash above.

## Runtime evidence (S13 API, 2026-11-17 14:24 MSK)

- Display: 1920x1080, DPR 1. Eight CPU logical cores. CPU package/core/display 52?C; max/min perf 84/42%; current/scaling/hardware max 3.109/3.192/3.400 GHz; turbo OFF; governor `schedutil`.
- GPU: 100% util, 65?C, 4799/6144 MiB VRAM, 79.4/90 W; default/max 125/135 W; 10.6 W headroom; 1935 MHz graphics / 6801 MHz memory; fan 58%; no throttle reason at sample time.
- RAM: 40%, 12.6/31.3 GB; swap 0.6 GB. Fan RPM telemetry absent (`?/?`). `/` 63%, `/data` 29% (40?C).
- Assessment: `activating`, PID 503740, procurement 175614, `MODEL_INFERENCE`, elapsed 21s; active job attributed to GPU. Feeder `active`; normalization `OFF`; autonomous worker `failed`.
- Today cohort (denominator 38): received 38; accepted 5; rejected 5; processing 2; error 26. Needs research 5/5 actionable denominator; normalization 0/0 parsed rows; ready cards 0/38.
- Commercial: 1742 total; open 284; awarded 1458. Open medal counts: Gold 3, Silver 19, Bronze 156, Wood 106. Awarded: Gold 127, Silver 847, Bronze 183, Wood 301.

## Verification

- `pytest -q tests/test_s13_kiosk_multi_screen.py`: 24 passed.
- `python -m py_compile deploy/s13_dashboard3.py`: PASS. JS syntax is covered by Node `--check` test. `git diff --check`: PASS.
- Controller tests verify NOW ? RESOURCES ? NOW ? COMMERCIAL, manual selection, 30-second hold, and critical override. Physical number-key selection 2 and 3 changed the S13 window title to RESOURCES and COMMERCIAL. Sampled physical title sequence included RESOURCES, NOW, and COMMERCIAL.
- Final S13 captures at [NOW](../../reports/s13_multiscreen_now_final.png), [RESOURCES](../../reports/s13_multiscreen_resources_final.png), and [COMMERCIAL](../../reports/s13_multiscreen_commercial_final.png). The latter two show GPU/open-medal panels clipped at the viewport edges; NOW also orders its pipeline incorrectly and clips the attention cards. These are acceptance failures, not passing screenshots.
- `SCREEN_NOW=FAIL`; `SCREEN_RESOURCES=FAIL`; `SCREEN_COMMERCIAL=FAIL`; `NO_HORIZONTAL_SCROLL=FAIL`; `PHYSICAL_DISPLAY_ACCEPTANCE=FAIL`. Commit: recorded on the isolated kiosk branch. The active navigation and screen title switch, but the layout is not fit for the physical display.

## Hard gates

- `BUSINESS_LOGIC_CHANGE=NO`; `COMMERCIAL_LOGIC_CHANGE=NO`; `ROUTING_LOGIC_CHANGE=NO`; `MODEL_LOGIC_CHANGE=NO`; `DOCUMENT_PIPELINE_LOGIC_CHANGE=NO`; `DB_MUTATION=NO`; `CRM_RESTARTED=NO`.
- `SCREEN_COUNT=3`; `MANUAL_SWITCH=PASS`; 30-second manual hold and critical override pass focused controller tests.
- `GPU_OWNER_VISIBLE`, complete resource visual fit, commercial visual fit, and overall physical acceptance are not signed off while the shown panels remain clipped.

## Follow-up

Investigate computed browser layout on the physical Firefox profile (including effective CSS direction, screen element bounds, and viewport client dimensions) before another deploy. Use a screenshot-driven browser diagnostic, fix only kiosk presentation, then repeat all three captures and no-scroll checks before declaring PASS.
