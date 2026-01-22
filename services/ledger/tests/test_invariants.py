"""
Ledger invariant tests.

These are the tests that must never be "fixed" by relaxing an assertion. If a
change makes one of these fail, the change is wrong, not the test.
"""

import pytest

from services.ledger.entries import (
    Account,
    Direction,
    Ledger,
    LedgerError,
    Posting,
    Transaction,
    captured_total,
    post_capture,
    post_refund,
    refunded_total,
)


def test_balanced_transaction_is_accepted():
    txn = Transaction(
        kind="capture",
        reference="pay_ok",
        postings=(
            Posting(Account.CARD_NETWORK_RECEIVABLE, Direction.DEBIT, 5_000),
            Posting(Account.MERCHANT_PAYABLE, Direction.CREDIT, 5_000),
        ),
    )
    assert txn.transaction_id.startswith("txn_")


def test_unbalanced_transaction_is_rejected():
    with pytest.raises(LedgerError, match="unbalanced"):
        Transaction(
            kind="capture",
            reference="pay_bad",
            postings=(
                Posting(Account.CARD_NETWORK_RECEIVABLE, Direction.DEBIT, 5_000),
                Posting(Account.MERCHANT_PAYABLE, Direction.CREDIT, 4_999),
            ),
        )


def test_float_amounts_are_rejected():
    """Money is integer minor units. A float here is a ledger break later."""
    with pytest.raises(LedgerError, match="minor units"):
        Posting(Account.CASH, Direction.DEBIT, 50.00)


def test_negative_and_zero_postings_are_rejected():
    with pytest.raises(LedgerError):
        Posting(Account.CASH, Direction.DEBIT, -100)
    with pytest.raises(LedgerError):
        Posting(Account.CASH, Direction.DEBIT, 0)


def test_capture_splits_fee_and_balances():
    ledger = Ledger()
    post_capture(ledger, reference="pay_1", amount_minor=10_000, fee_minor=290)

    assert captured_total(ledger, "pay_1") == 10_000
    assert ledger.balance(Account.MERCHANT_PAYABLE) == -9_710
    assert ledger.balance(Account.FEE_REVENUE) == -290
    assert ledger.is_balanced()


def test_fee_cannot_exceed_capture():
    ledger = Ledger()
    with pytest.raises(LedgerError, match="fee cannot"):
        post_capture(ledger, reference="pay_2", amount_minor=100, fee_minor=100)


def test_book_stays_balanced_across_capture_and_refund():
    ledger = Ledger()
    post_capture(ledger, reference="pay_3", amount_minor=25_000, fee_minor=725)
    assert ledger.is_balanced()

    post_refund(ledger, reference="pay_3", fee_minor=725)
    assert ledger.is_balanced()
    assert refunded_total(ledger, "pay_3") == 25_000
    # Fully refunded: every account nets back to zero.
    assert all(ledger.balance(a) == 0 for a in Account)


def test_refund_without_capture_is_rejected():
    ledger = Ledger()
    with pytest.raises(LedgerError, match="nothing captured"):
        post_refund(ledger, reference="pay_missing", fee_minor=0)


def test_double_refund_is_rejected():
    ledger = Ledger()
    post_capture(ledger, reference="pay_4", amount_minor=8_000, fee_minor=232)
    post_refund(ledger, reference="pay_4", fee_minor=232)
    with pytest.raises(LedgerError, match="already been refunded"):
        post_refund(ledger, reference="pay_4", fee_minor=232)


def test_posted_transactions_are_immutable():
    ledger = Ledger()
    txn = post_capture(ledger, reference="pay_5", amount_minor=1_000, fee_minor=29)
    with pytest.raises(Exception):
        txn.reference = "pay_tampered"  # frozen dataclass


def test_ledger_log_is_append_only():
    ledger = Ledger()
    post_capture(ledger, reference="pay_6", amount_minor=1_000, fee_minor=29)
    snapshot = ledger.transactions
    post_capture(ledger, reference="pay_7", amount_minor=2_000, fee_minor=58)
    # The earlier snapshot is unaffected -- history does not change underneath us.
    assert len(snapshot) == 1
    assert len(ledger.transactions) == 2
