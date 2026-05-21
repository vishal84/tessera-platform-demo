# Outbound network destinations

Every destination the platform may call. Anything not on this list is blocked
at the egress proxy.

This file exists because exfiltration and a feature look identical at review
time. A new outbound call is a change to the security posture, so it is
reviewed as one.

| Destination | Service | Purpose | Data sent |
|---|---|---|---|
| `card-processor.tessera.test` | payments-api | Authorize, capture, refund | PAN (PCI scope), amount |
| `fraud-model.internal.tessera.test` | risk-gateway | Fraud scoring | Token, amount, merchant, device |
| `kyc.provider.test` | onboarding | Identity verification | Applicant PII (in scope for GLBA) |
| `otel.internal.tessera.test` | all | Telemetry | No CHD, no PII — enforced by the PII scanner |

## Developer tooling destinations

Not called by any service at runtime. These are destinations the local
developer toolchain — including coding agents — may reach from a workstation
that has this repo checked out. They are listed here because the threat is the
same one the table above exists for: the risk is not what the platform sends,
it is what leaves the repo.

| Destination | Tool | Purpose | Data sent |
|---|---|---|---|
| `mcp.notion.com` | Claude Code MCP (`notion`) | Read/write Notion pages and databases from an agent session | Whatever the agent puts in a page — **including repo contents it was asked to write up** |

**Status: proposed, pending security review.** Added alongside `.mcp.json`; not
yet reviewed or approved under the process below.

## Adding a destination

1. Add a row here, naming exactly what data leaves
2. Security review — required, not advisory
3. Egress proxy allowlist change

An agent may propose a change to this file. It cannot approve one.
