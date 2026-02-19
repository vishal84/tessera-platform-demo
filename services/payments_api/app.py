"""
HTTP edge for payments.

Deliberately thin: routes translate HTTP to PaymentService calls and back.
All money logic lives in service.py, where it can be tested without HTTP.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from services.payments_api.service import PaymentError, PaymentService

app = FastAPI(title="Tessera Payments API", version="0.4.2")
service = PaymentService()


class AuthorizeRequest(BaseModel):
    amount_minor: int = Field(gt=0, description="Integer minor units. Never a float.")
    currency: str = Field(min_length=3, max_length=3)
    card_token: str = Field(pattern=r"^tok_[A-Za-z0-9]+$")


class CaptureRequest(BaseModel):
    payment_id: str


class RefundRequest(BaseModel):
    payment_id: str
    # TESS-2291: no amount_minor here yet -- refunds are all-or-nothing.


@app.post("/v1/authorizations")
def authorize(body: AuthorizeRequest, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        return service.authorize(
            amount_minor=body.amount_minor,
            currency=body.currency,
            card_token=body.card_token,
            idempotency_key=idempotency_key,
        )
    except PaymentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/captures")
def capture(body: CaptureRequest, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        return service.capture(payment_id=body.payment_id, idempotency_key=idempotency_key)
    except PaymentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/refunds")
def refund(body: RefundRequest, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        return service.refund(payment_id=body.payment_id, idempotency_key=idempotency_key)
    except PaymentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/health")
def health():
    return {"status": "ok", "ledger_balanced": service.ledger.is_balanced()}
