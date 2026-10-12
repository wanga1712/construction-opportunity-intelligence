"""Acceptance verification for Phase 6 Authority Hierarchy and Live Cards on S13."""
import json
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
from src.services.torgi_workset_service import get_evaluated_torgi_workset


def main():
    cards = get_evaluated_torgi_workset(hide_expired=True)
    print(f"TOTAL_EVALUATED_CARDS={len(cards)}")

    authorities = {}
    base_medals = {}
    eff_medals = {}
    model_medals = {}

    for c in cards:
        auth = c.get("base_medal_authority", "UNKNOWN")
        authorities[auth] = authorities.get(auth, 0) + 1
        
        bm = c.get("base_medal", "UNKNOWN")
        base_medals[bm] = base_medals.get(bm, 0) + 1
        
        em = c.get("effective_medal", "UNKNOWN")
        eff_medals[em] = eff_medals.get(em, 0) + 1
        
        mm = c.get("model_medal") or "UNASSESSED"
        model_medals[mm] = model_medals.get(mm, 0) + 1

    print(f"AUTHORITY_BREAKDOWN={json.dumps(authorities, ensure_ascii=False)}")
    print(f"BASE_MEDALS={json.dumps(base_medals, ensure_ascii=False)}")
    print(f"EFFECTIVE_MEDALS={json.dumps(eff_medals, ensure_ascii=False)}")
    print(f"MODEL_MEDALS={json.dumps(model_medals, ensure_ascii=False)}")

    print("\nTOP 10 CARDS IN WORKSET:")
    for i, c in enumerate(cards[:10], 1):
        eff = c.get("effective_medal")
        base = c.get("base_medal")
        auth = c.get("base_medal_authority")
        mod = c.get("model_medal")
        prelim = c.get("preliminary_medal")
        exp = c.get("expert_medal")
        decay = c.get("deadline_decay_steps")
        days = c.get("days_to_deadline")
        days_s = f"{days:.1f}d" if days is not None else "—"
        print(f"  {i:02d}. PID={c['id']} [{c.get('contract_number')}] -> Сейчас: {eff} (decay -{decay}, {days_s}) | Базовая: {base} ({auth}) | Модель: {mod} | Предварительно: {prelim} | Эксперт: {exp}")

if __name__ == "__main__":
    main()
