"""
Idempotency key storage for mutating payment endpoints.

Clients retry. Networks partition. Every mutating endpoint therefore takes an
`Idempotency-Key` header, and a replayed key must return the original result
rather than moving money a second time.

In production this is backed by Postgres (see migrations/0007_idempotency.sql).
The in-memory implementation here mirrors its semantics for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

KEY_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    response: dict
    created_at: datetime


class IdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}

    def get(self, key: str) -> dict | None:
        record = self._records.get(key)
        if record is None:
            return None
        if datetime.now(timezone.utc) - record.created_at > KEY_TTL:
            del self._records[key]
            return None
        return record.response

    def put(self, key: str, response: dict) -> None:
        self._records[key] = IdempotencyRecord(
            key=key, response=response, created_at=datetime.now(timezone.utc)
        )
