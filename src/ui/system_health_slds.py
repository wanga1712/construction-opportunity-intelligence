"""SLDS (Salesforce Lightning Design System) tokens, HTML components and charts.

UI-only helper for the system health page: no snapshot IO, no probes, no SSH.
Every HTML fragment is returned as a single line so Streamlit markdown never
treats it as an indented code block.
"""
from __future__ import annotations

import html
from string import Template
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import streamlit as st

BG = "#F3F2F2"
SURFACE = "#FFFFFF"
BORDER = "#DDDBDA"
PRIMARY = "#0176D3"
TEXT = "#080707"
LABEL = "#706E6B"
GRID = "#ECEBEA"
OK_BG, OK_FG = "#EBF7E6", "#04844B"
WARN_BG, WARN_FG, WARN_ACCENT = "#FEF3D6", "#8C4B02", "#FE8F10"
CRIT_BG, CRIT_FG, CRIT_ACCENT = "#FEE8E6", "#BA0517", "#EA001E"

CPU_CRIT_PCT = 90.0
CPU_WARN_PCT = 85.0
PROC_RED_PCT = 80.0

TONE_RU = {"ok": "Норма", "warn": "Внимание", "crit": "Критично", "info": "Инфо", "neutral": "Н/Д"}

_CSS_TEMPLATE = Template(
    """<style>
  :root { --slds-bg: $bg; --slds-surface: $surface; --slds-border: $border; --slds-primary: $primary;
    --slds-text: $text; --slds-label: $label; --slds-ok-fg: $ok_fg; --slds-warn-accent: $warn_accent;
    --slds-crit-accent: $crit_accent; --slds-radius: 4px; }
  [data-testid="stAppViewContainer"], [data-testid="stHeader"] { background: var(--slds-bg); }
  html, body, [data-testid="stAppViewContainer"] { font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif; color: var(--slds-text); }
  [data-testid="stSidebarNav"] { display: none !important; }
  .block-container { padding-top: 1.5rem; max-width: 1680px; }
  .slds-page-title { font-size: 26px; font-weight: 700; line-height: 1.2; margin: 0 0 2px 0; }
  .slds-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .0625em; color: var(--slds-label); }
  .slds-ribbon { display: flex; flex-wrap: wrap; gap: 10px 32px; align-items: center; background: $surface;
    border: 1px solid $border; border-radius: var(--slds-radius); padding: 12px 16px; margin: 10px 0 12px 0; }
  .slds-ribbon__item { display: flex; flex-direction: column; gap: 3px; }
  .slds-ribbon__val { font-size: 14px; font-weight: 600; }
  .slds-card { background: $surface; border: 1px solid $border; border-radius: var(--slds-radius); padding: 16px; margin-bottom: 12px; }
  .slds-card__head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px; }
  .slds-card__title { font-size: 17px; font-weight: 700; margin: 0; }
  .slds-card__role { font-size: 12px; color: var(--slds-label); }
  .slds-card__footer { font-size: 12px; color: var(--slds-label); border-top: 1px solid $grid; padding-top: 8px; margin-top: 12px; }
  .slds-badge { display: inline-block; padding: 1px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; line-height: 18px; white-space: nowrap; }
  .slds-badge--ok { background: $ok_bg; color: $ok_fg; }
  .slds-badge--warn { background: $warn_bg; color: $warn_fg; }
  .slds-badge--crit { background: $crit_bg; color: $crit_fg; }
  .slds-badge--info { background: #EAF5FE; color: #014486; }
  .slds-badge--neutral { background: $bg; color: #514F4D; border: 1px solid $border; }
  .slds-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
  .slds-kpi { background: $surface; border: 1px solid $border; border-radius: var(--slds-radius); padding: 16px; display: flex; flex-direction: column; gap: 4px; }
  .slds-kpi--warn { border-top: 3px solid $warn_accent; }
  .slds-kpi--crit { border-top: 3px solid $crit_accent; }
  .slds-kpi--ok { border-top: 3px solid $ok_fg; }
  .slds-kpi__value { font-size: 26px; font-weight: 700; line-height: 1.15; }
  .slds-kpi__value--crit { color: $crit_fg; }
  .slds-kpi__value--warn { color: $warn_fg; }
  .slds-kpi__sub { font-size: 12px; color: var(--slds-label); }
  .slds-kpi__badges { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }
  .slds-badges { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 12px; }
  .slds-badges__item { display: flex; align-items: center; gap: 6px; }
  .slds-meters { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px 20px; }
  .slds-meter__row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .slds-meter__val { font-size: 13px; font-weight: 600; }
  .slds-bar { height: 8px; border-radius: 4px; background: $bg; overflow: hidden; margin-top: 4px; }
  .slds-bar__fill { height: 100%; border-radius: 4px; }
  .slds-bar__fill--ok { background: $ok_fg; }
  .slds-bar__fill--warn { background: $warn_accent; }
  .slds-bar__fill--crit { background: $crit_accent; }
  .slds-bar__fill--neutral { background: var(--slds-primary); }
  .slds-sub { font-size: 11px; color: var(--slds-label); margin-top: 3px; }
  .slds-alert { background: $surface; border: 1px solid $border; border-left-width: 4px; border-radius: var(--slds-radius); padding: 12px 14px; margin-bottom: 8px; }
  .slds-alert--warn { border-left-color: $warn_accent; }
  .slds-alert--crit { border-left-color: $crit_accent; }
  .slds-alert--ok { border-left-color: $ok_fg; }
  .slds-alert--neutral { border-left-color: $border; }
  .slds-alert__head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 4px; }
  .slds-alert__title { font-size: 14px; font-weight: 700; }
  .slds-alert__line { font-size: 12px; color: #514F4D; }
  .slds-alert__meta { font-size: 11px; color: var(--slds-label); margin-top: 5px; }
  .slds-svc { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 0; border-bottom: 1px solid $grid; }
  .slds-svc:last-child { border-bottom: none; }
  .slds-svc__name { font-size: 13px; font-weight: 600; }
  .slds-svc__note { font-size: 11px; color: var(--slds-label); }
  .slds-empty { font-size: 12px; color: var(--slds-label); }
  [data-testid="stRadio"] div[role="radiogroup"] { gap: 8px; flex-wrap: wrap; row-gap: 6px; }
  [data-testid="stRadio"] div[role="radiogroup"] > label { background: $surface; border: 1px solid $border;
    border-radius: 16px; padding: 3px 14px; margin: 0; font-size: 13px; }
  [data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) { background: #EAF5FE; border-color: $primary; font-weight: 600; }
  [data-testid="stRadio"] div[role="radiogroup"] > label > div:first-child { display: none; }
  [data-testid="stDataFrame"] { border: 1px solid $border; border-radius: 4px; }
  [data-testid="stExpander"] details { border: 1px solid $border; border-radius: 4px; background: $surface; }
</style>"""
).substitute(
    bg=BG,
    surface=SURFACE,
    border=BORDER,
    primary=PRIMARY,
    text=TEXT,
    label=LABEL,
    grid=GRID,
    ok_bg=OK_BG,
    ok_fg=OK_FG,
    warn_bg=WARN_BG,
    warn_fg=WARN_FG,
    warn_accent=WARN_ACCENT,
    crit_bg=CRIT_BG,
    crit_fg=CRIT_FG,
    crit_accent=CRIT_ACCENT,
)

SLDS_CSS = _CSS_TEMPLATE

_STATUS_TONES = {
    "OK": "ok",
    "CURRENT": "ok",
    "PASSED": "ok",
    "SUCCESS": "ok",
    "ACTIVE": "ok",
    "RUNNING": "ok",
    "TIMER_HEALTHY": "ok",
    "ONESHOT_RUNNING": "ok",
    "ONESHOT_IDLE": "ok",
    "WARNING": "warn",
    "STALE": "warn",
    "UNREACHABLE": "warn",
    "COLLECTOR_FAILED": "warn",
    "PAUSED": "neutral",
    "UNKNOWN": "neutral",
    "N/A": "neutral",
    "DATA_UNAVAILABLE": "neutral",
    "INFO": "info",
    "CRITICAL": "crit",
    "COLLECTOR_DOWN": "crit",
    "FAILED": "crit",
    "HOST_DOWN": "crit",
    "SERVICE_DOWN": "crit",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def status_tone(status: Optional[str]) -> str:
    return _STATUS_TONES.get((status or "UNKNOWN").upper(), "neutral")


def cpu_tone(pct: Optional[float]) -> str:
    if pct is None:
        return "neutral"
    if float(pct) >= CPU_CRIT_PCT:
        return "crit"
    if float(pct) >= CPU_WARN_PCT:
        return "warn"
    return "neutral"


def bar_tone(pct: Optional[float]) -> str:
    if pct is None:
        return "neutral"
    if float(pct) >= CPU_CRIT_PCT:
        return "crit"
    if float(pct) >= PROC_RED_PCT:
        return "warn"
    return "ok"


def badge(text: Any, tone: str = "neutral") -> str:
    return f'<span class="slds-badge slds-badge--{tone}">{esc(text)}</span>'


def status_badge(status: Optional[str], text: Optional[str] = None) -> str:
    return badge(text or status or "Н/Д", status_tone(status))


def meter(label: str, value_text: str, pct: Optional[float], tone: Optional[str] = None, sub: str = "") -> str:
    pct = 0.0 if pct is None else max(0.0, min(100.0, float(pct)))
    tone = tone or bar_tone(pct)
    sub_html = f'<div class="slds-sub">{esc(sub)}</div>' if sub else ""
    return (
        '<div class="slds-meter">'
        f'<div class="slds-meter__row"><span class="slds-label">{esc(label)}</span>'
        f'<span class="slds-meter__val">{esc(value_text)}</span></div>'
        f'<div class="slds-bar"><div class="slds-bar__fill slds-bar__fill--{tone}" style="width:{pct:.1f}%"></div></div>'
        f"{sub_html}</div>"
    )


def kpi_card(label: str, value: str, sub: str = "", tone: str = "neutral", badges: str = "", value_tone: bool = False) -> str:
    card_tone = f" slds-kpi--{tone}" if tone in ("warn", "crit", "ok") else ""
    value_tone_cls = f" slds-kpi__value--{tone}" if value_tone and tone in ("warn", "crit") else ""
    badges_html = f'<div class="slds-kpi__badges">{badges}</div>' if badges else ""
    return (
        f'<div class="slds-kpi{card_tone}"><span class="slds-label">{esc(label)}</span>'
        f'<div class="slds-kpi__value{value_tone_cls}">{esc(value)}</div>'
        f'<div class="slds-kpi__sub">{esc(sub)}</div>{badges_html}</div>'
    )


def card(title: str, body: str, *, role: str = "", badges: str = "", footer: str = "") -> str:
    head = f'<div class="slds-card__head"><h3 class="slds-card__title">{esc(title)}</h3>'
    if role:
        head += f'<span class="slds-card__role">{esc(role)}</span>'
    if badges:
        head += badges
    head += "</div>"
    foot = f'<div class="slds-card__footer">{esc(footer)}</div>' if footer else ""
    return f'<div class="slds-card">{head}{body}{foot}</div>'


def alert_card(title: str, *, tone: str = "warn", badges: str = "", lines: Sequence[str] = (), meta: str = "") -> str:
    body = "".join(f'<div class="slds-alert__line">{line}</div>' for line in lines)
    meta_html = f'<div class="slds-alert__meta">{esc(meta)}</div>' if meta else ""
    return (
        f'<div class="slds-alert slds-alert--{tone}"><div class="slds-alert__head">'
        f'<span class="slds-alert__title">{esc(title)}</span>{badges}</div>{body}{meta_html}</div>'
    )


def service_row(name: str, status_text: str, tone: str, note: str = "") -> str:
    note_html = f'<span class="slds-svc__note">{esc(note)}</span>' if note else ""
    return (
        f'<div class="slds-svc"><span class="slds-svc__name">{esc(name)}</span>'
        f'<span>{note_html} {badge(status_text, tone)}</span></div>'
    )


def badge_pair(label: str, text: str, tone: str) -> str:
    return f'<span class="slds-badges__item"><span class="slds-label">{esc(label)}</span>{badge(text, tone)}</span>'


def area_chart_spec(
    *,
    label: str,
    color: str = PRIMARY,
    x_domain: Optional[Sequence[str]] = None,
    y_max: Optional[float] = None,
    height: int = 190,
) -> Dict[str, Any]:
    """Vega-Lite area spec: Y axis is pinned to >= 0, X domain is explicit (shared)."""
    x_encoding: Dict[str, Any] = {
        "field": "ts",
        "type": "temporal",
        "axis": {"title": None, "format": "%H:%M", "labelColor": LABEL, "labelFontSize": 11, "grid": False, "tickCount": 6},
    }
    if x_domain:
        x_encoding["scale"] = {"domain": list(x_domain)}
    y_scale: Dict[str, Any] = {"zero": True, "domainMin": 0, "nice": True}
    if y_max is not None:
        y_scale["domainMax"] = float(y_max)
    return {
        "height": height,
        "background": "transparent",
        "mark": {"type": "area", "color": color, "opacity": 0.16, "line": {"color": color, "strokeWidth": 2}, "interpolate": "monotone"},
        "encoding": {
            "x": x_encoding,
            "y": {
                "field": "value",
                "type": "quantitative",
                "title": None,
                "axis": {"title": label, "titleColor": LABEL, "titleFontSize": 11, "labelColor": LABEL, "labelFontSize": 11, "gridColor": GRID, "tickCount": 5},
                "scale": y_scale,
            },
            "tooltip": [
                {"field": "ts", "type": "temporal", "title": "Время", "format": "%d.%m %H:%M"},
                {"field": "value", "type": "quantitative", "title": label},
            ],
        },
        "config": {"view": {"stroke": "transparent"}},
    }


def render_area_chart(
    points: List[Dict[str, Any]],
    *,
    label: str,
    y_max: Optional[float] = None,
    height: int = 190,
    color: str = PRIMARY,
) -> None:
    """Area chart with a non-negative Y axis and an X domain shared by all charts."""
    if not points:
        return
    stamps = [str(p.get("ts")) for p in points if p.get("ts")]
    spec = area_chart_spec(
        label=label,
        color=color,
        x_domain=[min(stamps), max(stamps)] if stamps else None,
        y_max=y_max,
        height=height,
    )
    st.vega_lite_chart(pd.DataFrame(points), spec, use_container_width=True)
