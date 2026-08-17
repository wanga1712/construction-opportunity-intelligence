\pset tuples_only on
\pset format unaligned

SELECT concat_ws('|',
    'ACTIVITY', pid, usename, application_name, client_addr::text, state,
    wait_event_type, wait_event,
    coalesce(age(clock_timestamp(), xact_start)::text, 'NO_XACT'),
    left(regexp_replace(query, E'[\n\r\t]+', ' ', 'g'), 240)
)
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
ORDER BY xact_start NULLS LAST, query_start;

SELECT concat_ws('|',
    'LOCK', l.pid, l.locktype, l.mode, l.granted,
    coalesce(c.relname, ''), l.transactionid::text
)
FROM pg_locks l
LEFT JOIN pg_class c ON c.oid = l.relation
WHERE l.pid <> pg_backend_pid()
ORDER BY l.granted, l.pid, l.locktype, l.mode;
