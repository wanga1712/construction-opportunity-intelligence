# WIP=CRM-V3-KIOSK-ONE-SCREEN-VISUAL-DENSITY-REBUILD-1

## Status: PARTIAL ? local visual rebuild complete; physical release blocked

Source: `feat/crm-v3-kiosk-multi-screen-command-center-1` at
`f77f946edaec46abd818a4f829ca95969237146d`.

The kiosk remains one persistent screen with the existing collector, API and
business semantics. This presentation-only update uses a compact current-task
and hardware hero, fixed 205/245/82 px upper rows at 1920x1080, a connected
today pipeline, a compact attention bar, five events, and an OPEN/AWARDED medal
table. Hardware metrics use the same existing read model.

## Local verification

- `python -m pytest tests/test_s13_kiosk_physical_layout.py -q`: 9 passed.
- Browser viewports: 1920x1080, 1366x768, 1280x720; document bounds and marked
  panel bounds pass. At 1920x1080, the measured content occupancy is at least
  55% for CURRENT, HARDWARE, PIPELINE, ATTENTION and COMMERCIAL.
- JavaScript syntax and `git diff --check`: pass.

## Visual measurements (Chromium fixture, 1920x1080)

- Screen count: 1; no navigation or secondary screen.
- Five semantic zones: CURRENT, HARDWARE, PIPELINE, ATTENTION, BOTTOM; the bottom
  contains the two visible EVENTS and COMMERCIAL panels.
- Content occupancy: CURRENT 55.9%, HARDWARE 74.1%, PIPELINE 82.9%, ATTENTION
  57.9%, COMMERCIAL 93.9%.
- All eight CPU cores render in a compact 4x2 grid; the pipeline has five stages
  with a continuous connector line; the commercial medal table has GOLD, SILVER,
  BRONZE and WOOD columns and OPEN/AWARDED rows; five latest events render.
- Document bounds: 1920x1080, OUTSIDE=0.

## Physical acceptance

BLOCKED. The user explicitly excluded Firefox interaction. The physical Firefox
window currently has the old HTML document loaded; updating that document
requires a page refresh. Therefore no deployment or service restart was done,
and a physical screenshot of this revision cannot be truthfully captured. The
read-only baseline still reports HDMI-0 at 1920x1080+0+0, Firefox 1920x1080+0+0,
viewport 1920x1080, DPR=1, and title audit `DOC 1920x1080 | OUTSIDE 0 | PIPE
01234`. These are baseline values, not acceptance evidence for the new page.

## Files

`deploy/s13_kiosk_main.html`, `tests/test_s13_kiosk_physical_layout.py`, this
WIP, and `docs/PROJECT_PLAN.md`. The requested `reports/s13_kiosk_visual_density_rebuild.png` is not created
until physical refresh and screenshot capture are authorized.
