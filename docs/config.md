# Configuration

Every environment variable the platform reads is documented here. A key that
is not in this file and in `.env.example` is not configuration — it is a
surprise waiting for an on-call engineer.

## How config changes work

1. Add the key and a placeholder to `.env.example`
2. Document it in the table below — what it does, who owns it, what happens if
   it is wrong
3. Raise a ticket for platform-security to set the real value in Vault

You cannot do step 3 yourself, and neither can an agent. Production secret
material is set by a human holding the entitlement for it. `.env` is blocked
by `.claude/hooks/protect_secrets.py` for reading and writing, by people and
by agents alike.

## Keys

| Key | Owner | Purpose | If wrong |
|---|---|---|---|
| `DATABASE_URL` | platform | Primary Postgres connection | Service will not start |
| `CARD_PROCESSOR_API_KEY` | payments | Auth to the card processor | All authorizations fail |
| `CARD_PROCESSOR_WEBHOOK_SECRET` | payments | Verifies inbound webhooks | Settlement webhooks rejected |
| `LEDGER_SIGNING_KEY` | ledger | Signs ledger entries for the audit trail | Entries unverifiable; audit finding |
| `FRAUD_MODEL_ENDPOINT` | risk | Fraud scoring service URL | Risk fails closed; authorizations decline |
| `FRAUD_MODEL_TOKEN` | risk | Auth to the fraud model | Risk fails closed; authorizations decline |
| `KYC_PROVIDER_API_KEY` | compliance | Identity verification | Onboarding blocked |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | platform | Telemetry export | Blind during an incident |

## Non-secret tuning

Values that change behaviour but are not secrets live in code, not in the
environment, so that changing one shows up in a diff and goes through review.

`services/risk_gateway/config.py` holds the timeouts, retry policy and cache
settings for the fraud-model call. Anything on the authorization path is worth
reviewing against the reliability rules in `CLAUDE.md`.
