-- Payment authorizations.

CREATE TABLE payments (
    payment_id    TEXT PRIMARY KEY,
    amount_minor  BIGINT      NOT NULL CHECK (amount_minor > 0),
    currency      CHAR(3)     NOT NULL,
    card_token    TEXT        NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'authorized',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT payments_status_valid
        CHECK (status IN ('authorized', 'captured', 'refunded', 'voided'))
);

-- Money is stored as BIGINT minor units. There is no NUMERIC column here and
-- there must never be a FLOAT one.
