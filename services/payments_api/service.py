"""
Payment operations: authorize, capture, refund, void.

The route layer in app.py is a thin shell over this module so the money logic
is testable without spinning up HTTP.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from services.ledger.entries import (
    Ledger,
    LedgerError,
    captured_total,
    post_capture,
    post_refund,
    refunded_total,
)
from services.payments_api.idempotency import IdempotencyStore
from services.risk_gateway.client import FraudClient, RiskDecision

logger = logging.getLogger("payments_api")

FEE_BPS = 290  # 2.90%


class PaymentError(Exception):
    pass


def _fee_for(amount_minor: int) -> int:
    return round(amount_minor * FEE_BPS / 10_000)


@dataclass
class Authorization:
    payment_id: str
    amount_minor: int
    currency: str
    card_token: str
    status: str = "authorized"


class PaymentService:
    def __init__(
        self,
        ledger: Ledger | None = None,
        idempotency: IdempotencyStore | None = None,
        fraud_client: FraudClient | None = None,
    ) -> None:
        self.ledger = ledger or Ledger()
        self.idempotency = idempotency or IdempotencyStore()
        self.fraud_client = fraud_client or FraudClient()
        self.authorizations: dict[str, Authorization] = {}

    # --- authorize ---------------------------------------------------------

    def authorize(
        self, *, amount_minor: int, currency: str, card_token: str, idempotency_key: str
    ) -> dict:
        cached = self.idempotency.get(idempotency_key)
        if cached is not None:
            return cached

        decision = self.fraud_client.score(
            card_token=card_token, amount_minor=amount_minor, currency=currency
        )
        if decision is RiskDecision.DECLINE:
            response = {"status": "declined", "reason": "risk_decline"}
            self.idempotency.put(idempotency_key, response)
            return response

        payment_id = f"pay_{uuid.uuid4().hex[:16]}"
        self.authorizations[payment_id] = Authorization(
            payment_id=payment_id,
            amount_minor=amount_minor,
            currency=currency,
            card_token=card_token,
        )
        logger.info("payment_authorized", extra={"payment_id": payment_id, "amount": amount_minor})

        response = {"payment_id": payment_id, "status": "authorized", "amount_minor": amount_minor}
        self.idempotency.put(idempotency_key, response)
        return response

    # --- capture -----------------------------------------------------------

    def capture(self, *, payment_id: str, idempotency_key: str) -> dict:
        cached = self.idempotency.get(idempotency_key)
        if cached is not None:
            return cached

        auth = self.authorizations.get(payment_id)
        if auth is None:
            raise PaymentError(f"unknown payment {payment_id!r}")
        if auth.status != "authorized":
            raise PaymentError(f"payment {payment_id!r} is {auth.status}, cannot capture")

        fee = _fee_for(auth.amount_minor)
        post_capture(
            self.ledger, reference=payment_id, amount_minor=auth.amount_minor, fee_minor=fee
        )
        auth.status = "captured"

        response = {
            "payment_id": payment_id,
            "status": "captured",
            "amount_minor": auth.amount_minor,
            "fee_minor": fee,
        }
        self.idempotency.put(idempotency_key, response)
        return response

    # --- refund ------------------------------------------------------------

    def refund(self, *, payment_id: str, idempotency_key: str) -> dict:
        """
        Refund a captured payment in full.

        TESS-2291: support needs partial refunds. Merchants split shipments and
        we currently make them refund the whole order and re-charge, which
        double-dings the cardholder's statement.
        """
        cached = self.idempotency.get(idempotency_key)
        if cached is not None:
            return cached

        auth = self.authorizations.get(payment_id)
        if auth is None:
            raise PaymentError(f"unknown payment {payment_id!r}")

        captured = captured_total(self.ledger, payment_id)
        if captured == 0:
            raise PaymentError(f"payment {payment_id!r} has not been captured")

        try:
            post_refund(self.ledger, reference=payment_id, fee_minor=_fee_for(captured))
        except LedgerError as exc:
            raise PaymentError(str(exc)) from exc

        auth.status = "refunded"
        response = {
            "payment_id": payment_id,
            "status": "refunded",
            "refunded_minor": refunded_total(self.ledger, payment_id),
        }
        self.idempotency.put(idempotency_key, response)
        return response
