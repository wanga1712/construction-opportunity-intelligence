#!/usr/bin/env python3
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

crm_dsn = {
    "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CRM_DB_PORT", "5432")),
    "dbname": os.getenv("CRM_DB_NAME", "crm"),
    "user": os.getenv("CRM_DB_USER", "crm_app"),
    "password": os.getenv("CRM_DB_PASSWORD", ""),
}

conn = psycopg2.connect(**crm_dsn)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# Inspect columns
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'crm_category_okpd_priors'
    ORDER BY ordinal_position
""")
cols = cur.fetchall()
print("COLUMNS:")
for c in cols:
    print(f"  {c['column_name']} ({c['data_type']})")

# Total counts
cur.execute("SELECT COUNT(*) as cnt FROM crm_category_okpd_priors")
total_rows = cur.fetchone()["cnt"]

cur.execute("SELECT COUNT(*) as cnt FROM crm_category_okpd_priors WHERE active = TRUE")
total_active = cur.fetchone()["cnt"]

print(f"\nTOTAL_ROWS={total_rows}")
print(f"TOTAL_ACTIVE_PRIORS={total_active}")

# Grouped by active, signal_role, match_type, prior_kind (if exists)
has_prior_kind = any(c['column_name'] == 'prior_kind' for c in cols)

if has_prior_kind:
    cur.execute("""
        SELECT signal_role, prior_kind, active, match_type, COUNT(*) as cnt
        FROM crm_category_okpd_priors
        GROUP BY signal_role, prior_kind, active, match_type
        ORDER BY active DESC, cnt DESC
    """)
    groups = cur.fetchall()
    print("\nGROUPED:")
    for g in groups:
        print(f"  active={g['active']}, signal_role={g['signal_role']}, prior_kind={g['prior_kind']}, match_type={g['match_type']}: {g['cnt']}")

    cur.execute("""
        SELECT prior_kind, COUNT(*) as cnt
        FROM crm_category_okpd_priors
        WHERE active = TRUE
        GROUP BY prior_kind
    """)
    by_kind = {r['prior_kind']: r['cnt'] for r in cur.fetchall()}
    print(f"\nACTIVE_BY_PRIOR_KIND={json.dumps(by_kind, ensure_ascii=False)}")
else:
    cur.execute("""
        SELECT signal_role, active, match_type, COUNT(*) as cnt
        FROM crm_category_okpd_priors
        GROUP BY signal_role, active, match_type
        ORDER BY active DESC, cnt DESC
    """)
    groups = cur.fetchall()
    print("\nGROUPED:")
    for g in groups:
        print(f"  active={g['active']}, signal_role={g['signal_role']}, match_type={g['match_type']}: {g['cnt']}")
    print("\nACTIVE_BY_PRIOR_KIND=NONE (column does not exist)")

cur.execute("""
    SELECT signal_role, COUNT(*) as cnt
    FROM crm_category_okpd_priors
    WHERE active = TRUE
    GROUP BY signal_role
""")
by_role = {r['signal_role']: r['cnt'] for r in cur.fetchall()}
print(f"ACTIVE_BY_SIGNAL_ROLE={json.dumps(by_role, ensure_ascii=False)}")

# Check distinct categories
cur.execute("""
    SELECT DISTINCT commercial_category_code
    FROM crm_category_okpd_priors
    WHERE active = TRUE
    ORDER BY commercial_category_code
""")
cats = [r['commercial_category_code'] for r in cur.fetchall()]
print(f"\nACTIVE_CATEGORIES ({len(cats)}): {cats}")

conn.close()
