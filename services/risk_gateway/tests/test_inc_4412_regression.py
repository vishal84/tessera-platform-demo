"""
Regression tests for INC-4412.

On 2026-09-17 a one-line change set `CACHE_TTL_SECONDS` to 0. The fraud-model
response cache was absorbing ~77% of scoring calls, so removing it multiplied
offered load on a tier-1 synchronous dependency by ~4.4x in the time it took
one deploy to roll. Retries without backoff turned that into a metastable
overload that did not recover on its own: ~41,300 authorizations were declined
by the fail-closed path across 2,184 merchants.

Nothing in the suite objected, because the capacity model was only ever run
against hand-written configs in `test_capacity.py` -- never against the values
the service actually ships with. These tests close that gap: they assert on
`config_from_module()`, so a config change that pushes the fraud model past
capacity fails CI rather than paging someone.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from services.risk_gateway import config
from services.risk_gateway.client import FraudClient, RiskDecision, _backoff_delay
from services.risk_gateway.simulation import config_from_module, simulate

# Observed in ops/incidents/INC-4412/. alert.json recorded success_rate 0.708
# and p99 8.47s; metrics.csv shows fraud_model_rps settling around 1100.
INCIDENT_SUCCESS_RATE = 0.708


# --------------------------------------------------------------------------
# The live config must not saturate the dependency. This is the regression.
# --------------------------------------------------------------------------

def test_live_config_does_not_saturate_the_fraud_model():
    """
    The shipped config, run through the capacity model, must leave headroom.

    This is the assertion that was missing on 2026-09-17. With
    CACHE_TTL_SECONDS = 0 it fails: utilization 7.22, success rate 70.8%.
    """
    result = simulate(config_from_module())
    assert not result.saturated, result.summary()
    assert result.utilization < 1.0, result.summary()


def test_live_config_meets_the_fraud_model_slo():
    """ops/slo.yaml: success >= 99.5%, p99 <= 1.0s on the auth path."""
    result = simulate(config_from_module())
    assert result.success_rate >= 0.995, result.summary()
    assert result.p99_latency_seconds <= 1.0, result.summary()


def test_live_config_does_not_amplify_its_own_load():
    """
    Retries must be a rounding error in steady state, not a multiplier.

    During the incident this was 2.67 attempts per call, which is what took a
    2.7x overload to 7.2x and made the bad state stable.
    """
    result = simulate(config_from_module())
    assert result.mean_attempts_per_call < 1.05, result.summary()


def test_live_config_keeps_the_cache_load_bearing():
    """
    The cache is capacity, not an optimisation.

    Without it the fraud model sees the full authorization rate. Pin a hit rate
    that actually absorbs load so that halving the TTL as a "tuning" change is
    a test failure rather than an incident.
    """
    result = simulate(config_from_module())
    assert result.cache_hit_rate > 0.5, result.summary()


# --------------------------------------------------------------------------
# Contributing factors, each of which is a CLAUDE.md reliability rule.
# --------------------------------------------------------------------------

def test_every_outbound_attempt_has_a_timeout():
    """
    Reliability rule 1. The edge budget is 8.5s; with no per-attempt timeout a
    single attempt can consume all of it, which is why the incident p99 pinned
    at the budget rather than at anything the dependency was doing.
    """
    assert config.REQUEST_TIMEOUT_SECONDS is not None
    assert 0 < config.REQUEST_TIMEOUT_SECONDS < 8.5


def test_retries_have_backoff_and_jitter():
    """Reliability rule 2. Naive retries amplify load exactly when it hurts."""
    assert config.RETRY_BACKOFF_BASE_SECONDS > 0
    assert config.RETRY_JITTER is True


def test_backoff_is_actually_jittered_in_the_client():
    """
    The flag has to reach the request path.

    Before this change `RETRY_JITTER` was read only by simulation.py and the
    ops console -- the client ignored it, so the capacity model could be made
    to look healthy by flipping a flag that changed nothing in production.
    """
    window = config.RETRY_BACKOFF_BASE_SECONDS * 2
    delays = {_backoff_delay(1) for _ in range(50)}
    assert len(delays) > 1, "jitter enabled but every delay is identical"
    assert all(0.0 <= d <= window for d in delays)


def test_circuit_breaker_flag_stays_off_while_it_is_unimplemented():
    """
    Guardrail, not a preference.

    simulation.py and services/console/health.py both credit this flag, but
    client.py has no breaker. Enabling it would turn the health tile green
    without changing a single request. If you are here because you implemented
    the breaker, delete this test in the same commit.
    """
    from services.risk_gateway import client

    source = __import__("inspect").getsource(client)
    assert "CIRCUIT_BREAKER_ENABLED" not in source, (
        "client.py now references the breaker -- implement it, then drop this test"
    )
    assert config.CIRCUIT_BREAKER_ENABLED is False, (
        "the breaker flag is credited by the capacity model but not implemented "
        "in client.py; turning it on makes the model and the console report "
        "protection that does not exist"
    )


# --------------------------------------------------------------------------
# Characterisation: what the incident configuration actually did.
# --------------------------------------------------------------------------

def test_the_incident_configuration_reproduces_the_observed_failure():
    """
    The exact config that was live at 14:02 UTC, against the capacity model.

    Reproducing the observed numbers is what took this from "the deploy looks
    related" to a root cause. The deploy record named 4b56e1d, a docstring-only
    commit; the change that mattered was b745a5a, two commits earlier in the
    same rollout.
    """
    incident = replace(
        config_from_module(),
        cache_ttl_seconds=0,
        retry_attempts=3,
        backoff_base_seconds=0.0,
        jitter=False,
        request_timeout_seconds=None,
    )
    result = simulate(incident)

    assert result.saturated
    assert result.cache_hit_rate == 0.0
    assert result.mean_attempts_per_call > 2.0, "retry amplification"
    assert result.success_rate == pytest.approx(INCIDENT_SUCCESS_RATE, abs=0.01)
    assert result.p99_latency_seconds == pytest.approx(8.5, abs=0.05)


def test_the_other_knobs_do_not_rescue_a_disabled_cache():
    """
    Timeouts and backoff bound the blast radius; they do not replace capacity.

    Worth pinning because the tempting reading of this incident is "we should
    have had better retry policy". With the fixed retry policy and no cache the
    dependency is still ~6x over capacity.
    """
    result = simulate(replace(config_from_module(), cache_ttl_seconds=0))
    assert result.saturated
    assert result.success_rate < 0.95


# --------------------------------------------------------------------------
# TESS-2287: the memory problem the incident change was trying to solve.
# --------------------------------------------------------------------------

def test_expired_entries_are_pruned_rather_than_accumulated():
    """
    The original bug behind the ~400MB resident set.

    `get` treated expired entries as misses but never removed them and `put`
    kept writing, so the dict only ever grew. Setting the TTL to 0 did not
    reclaim anything -- it disabled the cache while leaving the leak in place.
    """
    client = FraudClient(transport=lambda p, t: RiskDecision.APPROVE, cache_ttl_seconds=0.01)
    for n in range(20):
        client.score(card_token=f"tok_{n}", amount_minor=1000, currency="USD")
    assert len(client.cache) == 20

    time.sleep(0.03)
    for n in range(20):
        client.score(card_token=f"tok_{n}", amount_minor=1000, currency="USD")
    assert len(client.cache) == 20, "expired entries should be replaced, not stacked"


def test_the_module_default_ttl_actually_caches():
    """
    The cheapest test that would have caught this.

    Both existing cache tests in test_client.py construct FraudClient with an
    explicit `cache_ttl_seconds=120`, so they kept passing while the module
    constant that production uses was 0. This one takes the default.
    """
    calls = {"n": 0}

    def counting(payload, timeout):
        calls["n"] += 1
        return RiskDecision.APPROVE

    client = FraudClient(transport=counting)
    for _ in range(10):
        client.score(card_token="tok_same", amount_minor=1000, currency="USD")

    assert calls["n"] == 1, f"repeat scoring hit the fraud model {calls['n']} times"
    assert client.cache.hits == 9


def test_cache_is_bounded_by_entry_count():
    """Resident set is bounded by the cap, not by however many cards show up."""
    client = FraudClient(
        transport=lambda p, t: RiskDecision.APPROVE,
        cache_ttl_seconds=300,
        cache_max_entries=10,
    )
    for n in range(50):
        client.score(card_token=f"tok_{n}", amount_minor=1000, currency="USD")

    assert len(client.cache) == 10
    assert client.cache.evictions == 40
