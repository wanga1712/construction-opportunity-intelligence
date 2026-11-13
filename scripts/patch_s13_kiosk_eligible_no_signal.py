#!/usr/bin/env python3
"""Patch the live S13 kiosk preimage for one researchable daily cohort."""
from __future__ import annotations

import argparse
from pathlib import Path


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _replace_once(
        text,
        "          SELECT p.id,p.okpd_code,p.ai_assessed_at,\n",
        "          SELECT p.id,p.okpd_code,p.ai_assessed_at,p.ai_assessment_status,\n",
        "cohort select",
    )
    text = _replace_once(
        text,
        """          SELECT *,
                 admitted AND (
                   has_prior OR has_current
                   OR COALESCE(ai_assessed_at>=current_date,false)
                 ) AS actionable
            FROM recv
        )
        SELECT count(*),
               count(*) FILTER (WHERE actionable),
               count(*) FILTER (WHERE NOT actionable),
               count(*) FILTER (
                 WHERE actionable AND ai_assessed_at>=current_date
               )
          FROM signals
""",
        """          SELECT *,
                 admitted AND (
                   has_prior OR has_current
                   OR COALESCE(ai_assessed_at>=current_date,false)
                 ) AS with_initial_signal,
                 admitted AND NOT (
                   has_prior OR has_current
                   OR COALESCE(ai_assessed_at>=current_date,false)
                 ) AS without_initial_signal
            FROM recv
        )
        SELECT count(*),
               count(*) FILTER (WHERE admitted),
               count(*) FILTER (WHERE with_initial_signal),
               count(*) FILTER (WHERE without_initial_signal),
               count(*) FILTER (
                 WHERE admitted AND ai_assessed_at>=current_date
               ),
               count(*) FILTER (
                 WHERE admitted
                   AND COALESCE(ai_assessed_at>=current_date,false)=false
                   AND upper(coalesce(ai_assessment_status,'')) IN
                       ('RUNNING','QUEUED')
               )
          FROM signals
""",
        "cohort signal split",
    )
    text = _replace_once(
        text,
        """            out["today"]["actionable_from_received"]=i(cohort[0][1])
            out["today"]["no_commercial_signal"]=i(cohort[0][2])
            out["today"]["processed_from_received"]=i(cohort[0][3])
""",
        """            out["today"]["researchable_from_received"]=i(cohort[0][1])
            out["today"]["with_initial_signal"]=i(cohort[0][2])
            out["today"]["without_initial_signal"]=i(cohort[0][3])
            out["today"]["processed_from_received"]=i(cohort[0][4])
            out["today"]["in_progress_from_received"]=i(cohort[0][5])
""",
        "cohort result mapping",
    )
    text = _replace_once(
        text,
        """    actionable=today.get("actionable_from_received")
    processed=today.get("processed_from_received")
    daily_remaining=(max(0,actionable-processed)
                     if actionable is not None and processed is not None else None)
    daily_pct=(round(100.0*processed/actionable,1)
               if actionable not in (None,0) and processed is not None else None)
""",
        """    researchable=today.get("researchable_from_received")
    processed=today.get("processed_from_received")
    in_progress=today.get("in_progress_from_received")
    daily_remaining=(max(0,researchable-processed)
                     if researchable is not None and processed is not None else None)
    daily_pct=(round(100.0*processed/researchable,1)
               if researchable not in (None,0) and processed is not None else None)
""",
        "daily arithmetic",
    )
    text = _replace_once(
        text,
        """        "actionable_today":actionable,
        "no_commercial_signal":today.get("no_commercial_signal"),
        "daily_workload":actionable,
""",
        """        "researchable_today":researchable,
        "actionable_today":researchable,
        "with_initial_signal":today.get("with_initial_signal"),
        "without_initial_signal":today.get("without_initial_signal"),
        "no_commercial_signal":today.get("without_initial_signal"),
        "in_progress_from_day_work_set":in_progress,
        "daily_workload":researchable,
""",
        "daily payload",
    )
    text = _replace_once(
        text,
        """            "actionable":yesterday.get("actionable_from_received"),
""",
        """            "researchable":yesterday.get("researchable_from_received"),
            "with_initial_signal":yesterday.get("with_initial_signal"),
            "without_initial_signal":yesterday.get("without_initial_signal"),
""",
        "previous-day payload",
    )
    text = _replace_once(
        text,
        "grid-template-columns:repeat(5,minmax(0,1fr));gap:5px}.daily-kpi",
        "grid-template-columns:repeat(6,minmax(0,1fr));gap:5px}.daily-kpi",
        "daily grid",
    )
    old_line = next(
        (
            line
            for line in text.splitlines()
            if line.startswith(" $('daily_work').innerHTML=")
            and "Требуют обработки" in line
        ),
        None,
    )
    if old_line is None:
        raise RuntimeError("daily UI line not found")
    new_line = """ $('daily_work').innerHTML=`<div class="daily-kpis">${metric('Сегодня поступило',dw.received_today,delta(dw.received_today-prev.received||0))}${metric('С первичным сигналом',dw.with_initial_signal,'приоритет HIGH')}${metric('Без первичного сигнала',dw.without_initial_signal,'приоритет LOW')}${metric('Обработано',dw.processed_from_day_work_set,'та же сегодняшняя когорта')}${metric('В обработке',dw.in_progress_from_day_work_set,'сейчас в пайплайне')}${metric('Осталось',dw.remaining_from_day_work_set,'researchable − processed')}</div><div class="daily-progress"><div><div class="track"><span style="width:${barWidth}%;background:#2ea043"></span></div><div class="daily-meta"><span class="small">Прогресс исследования сегодняшней когорты</span><span class="daily-tail ${tailCls}">${tailText}</span></div></div><div class="pct">${dailyPct==null?'н/д':num1(dailyPct)+'%'}</div></div><div class="contour-note">Операционно · Routing backlog ${nn(dw.routing_backlog)} · Document queue pending ${nn(dw.document_queue_pending)}</div><div class="contour-note">Общий накопленный контур: ${nn(ctTotal.processed_total)} / ${nn(ctTotal.eligible_total)} · ${ctTotal.progress_pct==null?'н/д':num1(ctTotal.progress_pct)+'%'} · осталось ${nn(ctTotal.remaining_total)} · срез ${age==null?'н/д':age+' мин'} · ${ct.delta_source||'н/д'}</div>`;"""
    return text.replace(old_line, new_line, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.source)
    output = Path(args.output)
    patched = patch(source.read_text(encoding="utf-8"))
    output.write_text(patched, encoding="utf-8", newline="\n")
    print(f"patched={output} bytes={len(patched.encode('utf-8'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
