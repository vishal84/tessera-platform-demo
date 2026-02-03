"""
Capacity model for the fraud-model dependency.

Used for capacity planning, and -- more usefully -- to reproduce the
metastable failure mode that the risk gateway is prone to, deterministically
and in under a millisecond, so it can be asserted on in a regression test.

The model is a fixed-point iteration, because the failure mode is circular:

    cache misses -> more load -> queueing -> timeouts -> retries
                                                  ^            |
                                                  +------------+

That loop is the whole point. A system with headroom absorbs a perturbation;
a system whose retries amplify load faster than it drains has two stable
states, and the bad one does not recover on its own once entered. This is
why "just add retries" is not a reliability strategy.

Reference: Brooker, "Avoiding overload in distributed systems"; the AWS
Builders' Library article on timeouts, retries and backoff with jitter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GatewayConfig:
    """The knobs that matter, extracted so both states are expressible."""

    cache_ttl_seconds: float
    retry_attempts: int
    backoff_base_seconds: float
    jitter: bool
    request_timeout_seconds: float | None
    circuit_breaker_enabled: bool


@dataclass(frozen=True)
class Workload:
    authorizations_per_second: float = 420.0
    fraud_model_service_time_seconds: float = 0.045
    # Sized against observed steady-state demand.
    fraud_model_workers: int = 7
    # Fraction of scoring calls that repeat within a 5-minute window, and so
    # would be served from cache if the cache were alive.
    repeat_rate_at_full_ttl: float = 0.84
    # The API edge gives the whole authorization this long before giving up.
    edge_budget_seconds: float = 8.5


@dataclass(frozen=True)
class Result:
    offered_rps: float
    capacity_rps: float
    utilization: float
    cache_hit_rate: float
    mean_attempts_per_call: float
    p99_latency_seconds: float
    success_rate: float
    saturated: bool

    def summary(self) -> str:
        return (
            f"offered={self.offered_rps:7.1f} rps  capacity={self.capacity_rps:6.1f} rps  "
            f"utilization={self.utilization:5.2f}  cache_hit={self.cache_hit_rate:4.0%}  "
            f"attempts={self.mean_attempts_per_call:4.2f}  "
            f"p99={self.p99_latency_seconds:6.2f}s  success={self.success_rate:5.1%}"
        )


def _cache_hit_rate(ttl_seconds: float, workload: Workload) -> float:
    """Hit rate rises with TTL and asymptotes to the workload's repeat rate."""
    if ttl_seconds <= 0:
        return 0.0
    return workload.repeat_rate_at_full_ttl * (1 - math.exp(-ttl_seconds / 120.0))


def simulate(config: GatewayConfig, workload: Workload | None = None) -> Result:
    workload = workload or Workload()
    capacity = workload.fraud_model_workers / workload.fraud_model_service_time_seconds
    hit_rate = _cache_hit_rate(config.cache_ttl_seconds, workload)
    base_rps = workload.authorizations_per_second * (1 - hit_rate)

    # Per-attempt patience: an explicit timeout, else the whole edge budget.
    patience = config.request_timeout_seconds or workload.edge_budget_seconds

    # Fixed point: attempts drive load, load drives failure, failure drives attempts.
    attempts = 1.0
    per_attempt_failure = 0.0
    wait = workload.fraud_model_service_time_seconds

    for _ in range(200):
        offered = base_rps * attempts
        utilization = offered / capacity

        if utilization < 1.0:
            # M/M/c approximation: mean sojourn time under partial load.
            wait = workload.fraud_model_service_time_seconds / (1.0 - utilization)
        else:
            # Past saturation the queue grows without bound; every caller ends
            # up waiting out its full patience.
            wait = patience * 3.25

        # Exponential service tail: P(latency > patience).
        per_attempt_failure = min(0.999, math.exp(-patience / wait))

        if config.circuit_breaker_enabled and per_attempt_failure > 0.5:
            # Breaker opens: load is shed instead of amplified. Calls fail fast
            # (and we fail closed), but the dependency is given room to recover.
            attempts = 1.0
            break

        new_attempts = sum(per_attempt_failure**k for k in range(config.retry_attempts + 1))
        if abs(new_attempts - attempts) < 1e-9:
            attempts = new_attempts
            break
        attempts = new_attempts

    offered = base_rps * attempts
    utilization = offered / capacity
    saturated = utilization >= 1.0

    success_rate = 1.0 - per_attempt_failure ** (config.retry_attempts + 1)

    # Tail latency: the 99th percentile of one attempt, plus the time burned on
    # failed attempts before it, plus whatever backoff we chose to wait.
    p99_one_attempt = min(wait * math.log(100.0), patience)
    failed_attempts = max(0.0, attempts - 1.0)
    backoff_total = sum(
        config.backoff_base_seconds * (2**k) for k in range(int(round(failed_attempts)))
    )
    p99 = min(
        p99_one_attempt + failed_attempts * min(patience, p99_one_attempt) + backoff_total,
        workload.edge_budget_seconds,
    )

    return Result(
        offered_rps=offered,
        capacity_rps=capacity,
        utilization=utilization,
        cache_hit_rate=hit_rate,
        mean_attempts_per_call=attempts,
        p99_latency_seconds=p99,
        success_rate=success_rate,
        saturated=saturated,
    )


def config_from_module() -> GatewayConfig:
    """Read the live values out of services/risk_gateway/config.py."""
    from services.risk_gateway import config as live

    return GatewayConfig(
        cache_ttl_seconds=live.CACHE_TTL_SECONDS,
        retry_attempts=live.RETRY_ATTEMPTS,
        backoff_base_seconds=live.RETRY_BACKOFF_BASE_SECONDS,
        jitter=live.RETRY_JITTER,
        request_timeout_seconds=live.REQUEST_TIMEOUT_SECONDS,
        circuit_breaker_enabled=live.CIRCUIT_BREAKER_ENABLED,
    )


def _main(argv: list[str] | None = None) -> None:
    import argparse
    import json
    from dataclasses import asdict

    parser = argparse.ArgumentParser(
        prog="python -m services.risk_gateway.simulation",
        description="Run the capacity model against the live risk-gateway config.",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the config and result as one JSON object"
    )
    args = parser.parse_args(argv)

    config = config_from_module()
    result = simulate(config)
    if args.json:
        print(json.dumps({"config": asdict(config), "result": asdict(result)}))
    else:
        print("live config :", result.summary())


if __name__ == "__main__":
    _main()
