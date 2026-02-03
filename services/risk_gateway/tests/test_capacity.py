"""
Characterisation tests for the fraud-model capacity model.

These describe how the dependency behaves under different call policies.
They are characterisation tests, not SLO assertions.
"""

from services.risk_gateway.simulation import GatewayConfig, Workload, simulate

HEALTHY = GatewayConfig(
    cache_ttl_seconds=300,
    retry_attempts=2,
    backoff_base_seconds=0.05,
    jitter=True,
    request_timeout_seconds=1.0,
    circuit_breaker_enabled=True,
)


def test_healthy_config_has_headroom():
    result = simulate(HEALTHY)
    assert result.utilization < 1.0
    assert result.success_rate > 0.99
    assert not result.saturated


def test_utilization_falls_as_ttl_rises():
    """Longer TTLs serve more from cache, so less load reaches the dependency."""
    short = GatewayConfig(**{**HEALTHY.__dict__, "cache_ttl_seconds": 30})
    long = GatewayConfig(**{**HEALTHY.__dict__, "cache_ttl_seconds": 600})
    assert simulate(long).utilization < simulate(short).utilization


def test_unbounded_retries_amplify_load_under_saturation():
    """
    The failure mode worth understanding: once saturated, retries without
    backoff multiply offered load instead of recovering from it.
    """
    amplifying = GatewayConfig(
        cache_ttl_seconds=15,
        retry_attempts=4,
        backoff_base_seconds=0.0,
        jitter=False,
        request_timeout_seconds=2.0,
        circuit_breaker_enabled=False,
    )
    result = simulate(amplifying)
    assert result.mean_attempts_per_call > 2.0, "expected retry amplification"
    assert result.offered_rps > 2 * Workload().authorizations_per_second


def test_circuit_breaker_limits_amplification_but_is_not_a_fix():
    """
    A breaker stops one slow dependency from being turned into an outage by
    its own clients. It does not restore the capacity the cache was providing.
    """
    without = GatewayConfig(10, 4, 0.0, False, 2.0, False)
    with_breaker = GatewayConfig(10, 2, 0.05, True, 2.0, True)

    assert simulate(without).mean_attempts_per_call > 2.0
    assert simulate(with_breaker).mean_attempts_per_call == 1.0
    # Blast radius contained, root cause untouched.
    assert simulate(with_breaker).success_rate < 0.99


def test_timeout_is_what_bounds_the_tail():
    bounded = GatewayConfig(10, 2, 0.05, True, 1.0, True)
    unbounded = GatewayConfig(10, 2, 0.05, True, None, True)
    assert simulate(bounded).p99_latency_seconds < simulate(unbounded).p99_latency_seconds
