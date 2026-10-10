-- EIS RATE-LIMIT SAFETY V1
-- Additive only. Apply through the approved document_intelligence DDL route.

BEGIN;

CREATE TABLE IF NOT EXISTS eis_rate_limit_state (
    host                     text PRIMARY KEY,
    blocked_until            timestamptz,
    blocked_since            timestamptz,
    last_429_at              timestamptz,
    last_429_xid             text,
    last_retry_after         integer,
    last_probe_at            timestamptz,
    last_probe_status        text,
    consecutive_blocks       integer NOT NULL DEFAULT 0,
    updated_at               timestamptz NOT NULL DEFAULT NOW()
);

INSERT INTO eis_rate_limit_state (host)
VALUES ('zakupki.gov.ru')
ON CONFLICT (host) DO NOTHING;

CREATE TABLE IF NOT EXISTS eis_request_events (
    id                     bigserial PRIMARY KEY,
    host                   text NOT NULL,
    request_type           text NOT NULL,
    requested_at           timestamptz NOT NULL DEFAULT NOW(),
    finished_at            timestamptz,
    http_status            smallint,
    bytes_received         bigint,
    duration_ms            integer,
    url                    text,
    xid                    text,
    retry_after            integer,
    concurrency_at_start   integer,
    error_class            text
);

CREATE INDEX IF NOT EXISTS idx_eis_request_events_requested_at
    ON eis_request_events (requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_eis_request_events_status
    ON eis_request_events (http_status, requested_at DESC);

CREATE TABLE IF NOT EXISTS eis_file_events (
    id               bigserial PRIMARY KEY,
    host             text NOT NULL,
    requested_at     timestamptz NOT NULL DEFAULT NOW(),
    result           text NOT NULL,
    source_url       text,
    url_hash         text,
    file_name        text,
    bytes_received   bigint,
    error_class      text,
    http_status      smallint,
    retry_after      integer,
    xid              text,
    duration_ms      integer
);

CREATE INDEX IF NOT EXISTS idx_eis_file_events_requested_at
    ON eis_file_events (requested_at DESC);

CREATE TABLE IF NOT EXISTS eis_rate_limit_incidents (
    incident_id                       bigserial PRIMARY KEY,
    host                              text NOT NULL,
    first_429_at                      timestamptz NOT NULL,
    xid                               text,
    retry_after                       integer,
    requests_last_1m                  bigint,
    requests_last_5m                  bigint,
    requests_last_15m                 bigint,
    requests_last_60m                 bigint,
    files_last_1m                     bigint,
    files_last_5m                     bigint,
    files_last_60m                    bigint,
    bytes_last_60m                    bigint,
    active_downloads_at_429           integer,
    configured_max_downloads          integer,
    configured_stagger_ms             integer,
    block_started_at                  timestamptz,
    probe_at                          timestamptz,
    probe_result                      text,
    block_ended_at                    timestamptz,
    block_duration_minutes            numeric(12, 2),
    created_at                        timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eis_rate_limit_incidents_open
    ON eis_rate_limit_incidents (host, first_429_at DESC)
    WHERE block_ended_at IS NULL;

ALTER TABLE download_attempts
    ADD COLUMN IF NOT EXISTS response_headers jsonb,
    ADD COLUMN IF NOT EXISTS retry_after integer,
    ADD COLUMN IF NOT EXISTS xid text;

INSERT INTO download_throttle (id, last_start_at)
VALUES (1, NOW())
ON CONFLICT (id) DO NOTHING;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON eis_rate_limit_state, eis_request_events, eis_file_events,
       eis_rate_limit_incidents
    TO doc_worker;

GRANT USAGE, SELECT
    ON SEQUENCE eis_request_events_id_seq,
                eis_file_events_id_seq,
                eis_rate_limit_incidents_incident_id_seq
    TO doc_worker;

COMMIT;
