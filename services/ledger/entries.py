"""
Tessera double-entry ledger.

The source of truth for money. Two rules govern everything in this module:

  1. Every transaction balances -- total debits equal total credits.
  2. Posted entries are immutable. Corrections are new compensating entries.

Auditors read this ledger directly, so a "quick fix" that mutates history is
worse than the bug it fixes. See the `ledger-invariants` skill.

All amounts are integer minor units (cents). There are no floats in this file
and there must never be.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class Account(StrEnum):
    """Chart of accounts, trimmed to what the payments path touches."""

    CARD_NETWORK_RECEIVABLE = "card_network_receivable"  # asset
    MERCHANT_PAYABLE = "merchant_payable"                # liability
    CASH = "cash"                                        # asset
    FEE_REVENUE = "fee_revenue"                          # revenue
    REFUND_CLEARING = "refund_clearing"                  # liability


class LedgerError(Exception):
    """Raised when an operation would violate a ledger invariant."""


@dataclass(frozen=True)
class Posting:
    account: Account
    direction: Direction
    amount_minor: int

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise LedgerError(
                f"amount_minor must be int minor units, got {type(self.amount_minor).__name__}"
            )
        if self.amount_minor <= 0:
            raise LedgerError("postings must be positive; use Direction to express sign")


@dataclass(frozen=True)
class Transaction:
    """An immutable, balanced set of postings."""

    kind: str
    postings: tuple[Posting, ...]
    reference: str
    currency: str = "USD"
    transaction_id: str = field(default_factory=lambda: f"txn_{uuid.uuid4().hex[:16]}")
    posted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.postings:
            raise LedgerError("transaction must have at least two postings")
        debits = sum(p.amount_minor for p in self.postings if p.direction is Direction.DEBIT)
        credits = sum(p.amount_minor for p in self.postings if p.direction is Direction.CREDIT)
        if debits != credits:
            raise LedgerError(
                f"unbalanced transaction {self.kind!r}: "
                f"debits={debits} credits={credits} delta={debits - credits}"
            )
        if debits == 0:
            raise LedgerError("transaction must move a non-zero amount")


class Ledger:
    """Append-only transaction log."""

    def __init__(self) -> None:
        self._transactions: list[Transaction] = []

    def post(self, transaction: Transaction) -> Transaction:
        self._transactions.append(transaction)
        return transaction

    @property
    def transactions(self) -> tuple[Transaction, ...]:
        return tuple(self._transactions)

    def balance(self, account: Account) -> int:
        """Signed balance in minor units: debits positive, credits negative."""
        total = 0
        for txn in self._transactions:
            for posting in txn.postings:
                if posting.account is account:
                    total += (
                        posting.amount_minor
                        if posting.direction is Direction.DEBIT
                        else -posting.amount_minor
                    )
        return total

    def is_balanced(self) -> bool:
        """The whole book must net to zero. If it does not, we have a break."""
        return sum(self.balance(a) for a in Account) == 0

    def for_reference(self, reference: str) -> tuple[Transaction, ...]:
        return tuple(t for t in self._transactions if t.reference == reference)


# --- payment flows ---------------------------------------------------------


def post_capture(
    ledger: Ledger, *, reference: str, amount_minor: int, fee_minor: int
) -> Transaction:
    """Settle an authorization. Money moves from the network to the merchant."""
    if fee_minor >= amount_minor:
        raise LedgerError("fee cannot equal or exceed the captured amount")
    return ledger.post(
        Transaction(
            kind="capture",
            reference=reference,
            postings=(
                Posting(Account.CARD_NETWORK_RECEIVABLE, Direction.DEBIT, amount_minor),
                Posting(Account.MERCHANT_PAYABLE, Direction.CREDIT, amount_minor - fee_minor),
                Posting(Account.FEE_REVENUE, Direction.CREDIT, fee_minor),
            ),
        )
    )


def captured_total(ledger: Ledger, reference: str) -> int:
    """Total captured against a reference, in minor units."""
    return sum(
        p.amount_minor
        for txn in ledger.for_reference(reference)
        if txn.kind == "capture"
        for p in txn.postings
        if p.account is Account.CARD_NETWORK_RECEIVABLE and p.direction is Direction.DEBIT
    )


def refunded_total(ledger: Ledger, reference: str) -> int:
    """Total already refunded against a reference, in minor units."""
    return sum(
        p.amount_minor
        for txn in ledger.for_reference(reference)
        if txn.kind == "refund"
        for p in txn.postings
        if p.account is Account.CARD_NETWORK_RECEIVABLE and p.direction is Direction.CREDIT
    )


def post_refund(ledger: Ledger, *, reference: str, fee_minor: int) -> Transaction:
    """
    Return captured funds to the cardholder.

    NOTE: full refunds only. The merchant agreement allows partial refunds and
    support has been raising tickets about it for two quarters -- see
    TESS-2291. Not implemented yet.
    """
    captured = captured_total(ledger, reference)
    if captured == 0:
        raise LedgerError(f"nothing captured against {reference!r}; cannot refund")
    if refunded_total(ledger, reference) > 0:
        raise LedgerError(f"{reference!r} has already been refunded")

    return ledger.post(
        Transaction(
            kind="refund",
            reference=reference,
            postings=(
                Posting(Account.CARD_NETWORK_RECEIVABLE, Direction.CREDIT, captured),
                Posting(Account.MERCHANT_PAYABLE, Direction.DEBIT, captured - fee_minor),
                Posting(Account.FEE_REVENUE, Direction.DEBIT, fee_minor),
            ),
        )
    )
