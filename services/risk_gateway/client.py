"""
Client for the fraud model service.

This call sits on the synchronous authorization path: every card
authorization blocks on it. Anything slow here is slow for the cardholder at
the terminal, and anything that amplifies load here amplifies it against a
dependency that is already struggling.

Risk scoring fails CLOSED -- if we cannot get a decision we decline, because
approving an unscored transaction is how you find out about a card-testing
attack from your chargeback report.
"""

from __future__ import annotations

import logging
import random
import time
from enum import StrEnum

from services.risk_gateway import config

logger = logging.getLogger("risk_gateway")


class RiskDecision(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"
    REVIEW = "review"


class FraudModelUnavailable(Exception):
    pass


class _ResponseCache:
    """
    TTL cache with a bounded entry count.

    Both bounds matter. The TTL is what keeps offered load off the fraud model;
    the entry cap is what keeps the pod's resident set flat. Before INC-4412
    this class had neither an entry cap nor any pruning of expired entries --
    `get` treated them as misses but `put` kept writing, so the dict only ever
    grew. That is the memory growth TESS-2287 was chasing, and it is why
    setting the TTL to zero did not actually reclaim anything.
    """

    def __init__(self, ttl_seconds: float, max_entries: int | None = None) -> None:
        self.ttl = ttl_seconds
        self.max_entries = config.CACHE_MAX_ENTRIES if max_entries is None else max_entries
        self._entries: dict[str, tuple[float, RiskDecision]] = {}
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> RiskDecision | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        if (time.monotonic() - entry[0]) > self.ttl:
            # Drop it rather than leaving it to accumulate.
            del self._entries[key]
            self.misses += 1
            return None
        self.hits += 1
        return entry[1]

    def put(self, key: str, decision: RiskDecision) -> None:
        if self.max_entries <= 0:
            return
        # Re-insert so dict order tracks recency of write, oldest first.
        self._entries.pop(key, None)
        self._entries[key] = (time.monotonic(), decision)
        while len(self._entries) > self.max_entries:
            del self._entries[next(iter(self._entries))]
            self.evictions += 1


def _default_transport(payload: dict, timeout: float | None) -> RiskDecision:
    raise FraudModelUnavailable("no transport configured; inject one in tests")


def _backoff_delay(attempt: int) -> float:
    """
    Exponential backoff with full jitter.

    Jitter is not decoration. Without it every caller that failed at the same
    moment retries at the same moment, which is how a dependency that is merely
    slow gets hit by a synchronised wave and stays down. Full jitter spreads
    the retries uniformly across the window instead of bunching them at its
    edge. See the AWS Builders' Library article referenced in simulation.py.
    """
    window = config.RETRY_BACKOFF_BASE_SECONDS * (2**attempt)
    if window <= 0:
        return 0.0
    return random.uniform(0.0, window) if config.RETRY_JITTER else window


class FraudClient:
    """
    Scores a transaction against the fraud model.

    `transport` is injectable so tests and the capacity model in
    simulation.py can drive it without a network.
    """

    def __init__(
        self,
        transport=None,
        cache_ttl_seconds: float | None = None,
        cache_max_entries: int | None = None,
    ) -> None:
        self.transport = transport or _default_transport
        self.max_connections = config.MAX_CONNECTIONS
        self.in_flight = 0
        self.cache = _ResponseCache(
            config.CACHE_TTL_SECONDS if cache_ttl_seconds is None else cache_ttl_seconds,
            cache_max_entries,
        )
        self.attempts_made = 0

    @staticmethod
    def _cache_key(card_token: str, amount_minor: int, currency: str) -> str:
        return f"{card_token}:{amount_minor}:{currency}"

    def score(self, *, card_token: str, amount_minor: int, currency: str) -> RiskDecision:
        """Score a transaction. Raises rather than returning a decision on failure."""
        key = self._cache_key(card_token, amount_minor, currency)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        payload = {"card_token": card_token, "amount_minor": amount_minor, "currency": currency}
        last_error: Exception | None = None

        for attempt in range(config.RETRY_ATTEMPTS + 1):
            self.attempts_made += 1
            if self.in_flight >= self.max_connections:
                raise FraudModelUnavailable(
                    f"connection pool exhausted ({self.max_connections} in use)"
                )
            self.in_flight += 1
            try:
                decision = self.transport(payload, config.REQUEST_TIMEOUT_SECONDS)
                self.cache.put(key, decision)
                return decision
            except FraudModelUnavailable as exc:
                last_error = exc
                logger.warning(
                    "fraud_model_attempt_failed",
                    extra={"attempt": attempt, "error": str(exc)},
                )
                if attempt < config.RETRY_ATTEMPTS:
                    time.sleep(_backoff_delay(attempt))
            finally:
                self.in_flight = max(0, self.in_flight - 1)

        logger.error("fraud_model_exhausted", extra={"attempts": config.RETRY_ATTEMPTS + 1})
        raise FraudModelUnavailable(
            f"fraud model unavailable after {config.RETRY_ATTEMPTS + 1} attempts"
        ) from last_error
