-- P0 EIS_GUARD_AUTO_RECOVERY_V2: remember stale canary URLs so the recovery
-- probe rotates instead of treating a saved 404 as a network failure.

CREATE TABLE IF NOT EXISTS eis_canary_stale_urls (
    url_hash    text PRIMARY KEY,
    url         text NOT NULL,
    last_status integer,
    marked_at   timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON eis_canary_stale_urls TO doc_worker;

COMMENT ON TABLE eis_canary_stale_urls IS
    'canary URLs that answered 404/410; skipped by resolve_canary_candidates()';
