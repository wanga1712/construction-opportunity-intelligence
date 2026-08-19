import subprocess

queries = [
    ("active_conns", "SELECT count(*) FROM pg_stat_activity WHERE state='active'"),
    ("total_conns", "SELECT count(*) FROM pg_stat_activity"),
    ("tx_rate", "SELECT sum(xact_commit+xact_rollback) FROM pg_stat_database WHERE datname='tender_monitor'"),
    ("pg_locks", "SELECT count(*) FROM pg_locks"),
]

for name, q in queries:
    result = subprocess.check_output(
        ["sudo", "-n", "-u", "postgres", "psql", "-d", "tender_monitor", "-At", "-c", q],
        text=True
    ).strip()
    print(f"{name}={result}")
