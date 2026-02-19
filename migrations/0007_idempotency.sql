-- Idempotency keys for mutating payment endpoints.
--
-- A client that retries must not move money twice. The key is supplied by the
-- client and the response is stored against it.

CREATE TABLE idempotency_keys (
    key          TEXT PRIMARY KEY,
    response     JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idempotency_keys_created_at_idx ON idempotency_keys (created_at);

-- Keys expire after 24h; a nightly job prunes them.
