from services.risk_gateway.client import FraudClient, FraudModelUnavailable, RiskDecision


def test_score_returns_transport_decision():
    client = FraudClient(transport=lambda payload, timeout: RiskDecision.APPROVE)
    assert client.score(card_token="tok_a", amount_minor=1000, currency="USD") is RiskDecision.APPROVE


def test_repeat_scoring_is_served_from_cache():
    client = FraudClient(transport=lambda p, t: RiskDecision.APPROVE, cache_ttl_seconds=120)
    for _ in range(5):
        client.score(card_token="tok_same", amount_minor=1000, currency="USD")
    assert client.cache.hits == 4
    assert client.cache.misses == 1


def test_distinct_transactions_are_not_conflated():
    client = FraudClient(transport=lambda p, t: RiskDecision.APPROVE, cache_ttl_seconds=120)
    client.score(card_token="tok_a", amount_minor=1000, currency="USD")
    client.score(card_token="tok_b", amount_minor=1000, currency="USD")
    client.score(card_token="tok_a", amount_minor=2000, currency="USD")
    assert client.cache.hits == 0
    assert client.cache.misses == 3


def test_risk_scoring_fails_closed():
    """If we cannot get a decision, we must not approve."""
    def always_down(payload, timeout):
        raise FraudModelUnavailable("upstream 503")

    client = FraudClient(transport=always_down)
    try:
        client.score(card_token="tok_b", amount_minor=1000, currency="USD")
    except FraudModelUnavailable:
        pass
    else:
        raise AssertionError("must not return a decision when the model is unavailable")


def test_every_failure_is_retried_the_configured_number_of_times():
    calls = {"n": 0}

    def always_down(payload, timeout):
        calls["n"] += 1
        raise FraudModelUnavailable("upstream 503")

    client = FraudClient(transport=always_down)
    try:
        client.score(card_token="tok_c", amount_minor=1000, currency="USD")
    except FraudModelUnavailable:
        pass
    from services.risk_gateway import config
    assert calls["n"] == config.RETRY_ATTEMPTS + 1
