import pytest

from services.ledger.entries import Account
from services.payments_api.service import PaymentError, PaymentService
from services.risk_gateway.client import FraudClient, RiskDecision


def make_service(decision: RiskDecision = RiskDecision.APPROVE) -> PaymentService:
    return PaymentService(fraud_client=FraudClient(transport=lambda p, t: decision))


def authorize_and_capture(svc: PaymentService, amount: int = 10_000) -> str:
    auth = svc.authorize(
        amount_minor=amount, currency="USD", card_token="tok_demo", idempotency_key="k-auth"
    )
    svc.capture(payment_id=auth["payment_id"], idempotency_key="k-cap")
    return auth["payment_id"]


def test_authorize_returns_payment_id():
    svc = make_service()
    result = svc.authorize(
        amount_minor=5_000, currency="USD", card_token="tok_demo", idempotency_key="k1"
    )
    assert result["status"] == "authorized"
    assert result["payment_id"].startswith("pay_")


def test_risk_decline_blocks_authorization():
    svc = make_service(RiskDecision.DECLINE)
    result = svc.authorize(
        amount_minor=5_000, currency="USD", card_token="tok_demo", idempotency_key="k2"
    )
    assert result["status"] == "declined"
    assert not svc.authorizations


def test_replayed_idempotency_key_returns_the_original_response():
    svc = make_service()
    first = svc.authorize(
        amount_minor=5_000, currency="USD", card_token="tok_demo", idempotency_key="same"
    )
    second = svc.authorize(
        amount_minor=5_000, currency="USD", card_token="tok_demo", idempotency_key="same"
    )
    assert first == second
    assert len(svc.authorizations) == 1


def test_capture_posts_a_balanced_ledger_entry():
    svc = make_service()
    payment_id = authorize_and_capture(svc, 10_000)
    assert svc.ledger.is_balanced()
    assert svc.ledger.balance(Account.FEE_REVENUE) == -290
    assert svc.authorizations[payment_id].status == "captured"


def test_capture_is_idempotent_on_replay():
    svc = make_service()
    auth = svc.authorize(
        amount_minor=10_000, currency="USD", card_token="tok_demo", idempotency_key="k-a"
    )
    svc.capture(payment_id=auth["payment_id"], idempotency_key="k-c")
    svc.capture(payment_id=auth["payment_id"], idempotency_key="k-c")
    # One capture transaction, not two.
    assert len(svc.ledger.transactions) == 1


def test_refund_returns_the_full_captured_amount():
    svc = make_service()
    payment_id = authorize_and_capture(svc, 10_000)
    result = svc.refund(payment_id=payment_id, idempotency_key="k-ref")

    assert result["refunded_minor"] == 10_000
    assert svc.ledger.is_balanced()
    assert all(svc.ledger.balance(a) == 0 for a in Account)


def test_refund_before_capture_is_rejected():
    svc = make_service()
    auth = svc.authorize(
        amount_minor=10_000, currency="USD", card_token="tok_demo", idempotency_key="k-a"
    )
    with pytest.raises(PaymentError, match="not been captured"):
        svc.refund(payment_id=auth["payment_id"], idempotency_key="k-r")


def test_second_refund_is_rejected():
    svc = make_service()
    payment_id = authorize_and_capture(svc, 10_000)
    svc.refund(payment_id=payment_id, idempotency_key="k-r1")
    with pytest.raises(PaymentError, match="already been refunded"):
        svc.refund(payment_id=payment_id, idempotency_key="k-r2")


@pytest.mark.xfail(reason="TESS-2291: partial refunds not implemented yet", strict=True)
def test_partial_refund_is_supported():
    """
    Support raises this every week. Merchants split shipments and need to
    refund one line, not the whole order.
    """
    svc = make_service()
    payment_id = authorize_and_capture(svc, 10_000)
    result = svc.refund(payment_id=payment_id, amount_minor=3_000, idempotency_key="k-partial")
    assert result["refunded_minor"] == 3_000
