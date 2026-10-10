"""Что показывает таблица по медалям vs что лежит в возможностях (для закупок «Поставка …»)."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

NUMBERS = [
    "0330100001126000018",  # светильники светодиодные
    "0330100001126000019",  # прожекторы/лампы
    "0330800001726000045",  # цветочная продукция
    "0330200022326000039",  # лампы бактерицидные
    "0136500001126005470",  # проектор
    "0813500000126018762",  # лампа светодиодная
    "0818500007326000037",  # ИБП
    "0318300082526000005",  # системные блоки
    "0318300225826000017",  # ПК в сборе
    "0848300064126000353",  # интерактивное оборудование
    "32616445095",          # сервер (контрольная)
]

kw = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(**kw)
try:
    with conn.cursor() as cur:
        for number in NUMBERS:
            cur.execute("select id, auction_name from crm_procurements where contract_number = %s", (number,))
            row = cur.fetchone()
            if not row:
                print("%-22s НЕТ В CRM" % number)
                continue
            pid, name = row
            cur.execute(
                """SELECT commercial_category_code, opportunity_track, commercial_state, status,
                          candidate_medal, current_effective_medal, candidate_initial_medal,
                          current_effective_score, current_effective_reason
                   FROM crm_procurement_category_opportunities
                   WHERE procurement_id = %s ORDER BY commercial_priority_score DESC NULLS LAST""",
                (pid,),
            )
            opps = cur.fetchall()
            scope = None
            cur.execute("select procurement_scope_type, admission_state from crm_procurement_scope_authority where procurement_id=%s", (pid,))
            scope = cur.fetchone()
            print("%-22s pid=%-7s %s" % (number, pid, (name or "")[:60]))
            print("    scope=%s" % (scope,))
            for opp in opps:
                print("    cat=%-26s track=%-18s state=%-10s cand=%-8s eff=%-8s init=%-8s score=%s reason=%s" % (
                    opp[0], opp[1], opp[2], opp[4], opp[5], opp[6], opp[7], (opp[8] or "")[:40]))
finally:
    conn.close()
