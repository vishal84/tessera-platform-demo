"""
Point-in-time guarantees for ml/features/aggregates.py.

The frame below is small enough to reason about by hand. Card A has four
transactions; the first and last are disputed. Card B is a bystander.

    row  card  timestamp            chargeback_filed_at
    t1   A     2026-01-01 00:00     2026-02-15
    t2   A     2026-02-01 00:00     -
    t3   A     2026-03-01 00:00     -
    t4   A     2026-03-01 12:00     2026-04-30
    t5   B     2026-02-20 00:00     -
"""

import numpy as np
import pandas as pd
import pytest

from ml.features.aggregates import (
    AGGREGATE_FEATURES,
    build,
    card_chargeback_rate,
    nightly_batch_as_of,
)


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "transaction_id": ["t1", "t2", "t3", "t4", "t5"],
            "card_token": ["tok_A", "tok_A", "tok_A", "tok_A", "tok_B"],
            "timestamp": pd.to_datetime(
                [
                    "2026-01-01T00:00:00Z",
                    "2026-02-01T00:00:00Z",
                    "2026-03-01T00:00:00Z",
                    "2026-03-01T12:00:00Z",
                    "2026-02-20T00:00:00Z",
                ],
                utc=True,
            ),
            "chargeback_filed_at": pd.to_datetime(
                ["2026-02-15T00:00:00Z", None, None, "2026-04-30T00:00:00Z", None], utc=True
            ),
            "is_fraud": [1, 0, 0, 1, 0],
        }
    ).set_index("transaction_id")


def strict(frame: pd.DataFrame) -> pd.Series:
    return card_chargeback_rate(frame, frame["timestamp"])


def test_a_chargeback_is_invisible_until_it_is_filed(frame):
    # t2 happens on Feb 1; t1's dispute is not filed until Feb 15.
    assert strict(frame)["t2"] == 0.0


def test_a_chargeback_counts_once_it_has_been_filed(frame):
    out = strict(frame)
    assert out["t3"] == pytest.approx(1 / 2)  # history {t1, t2}, one filed dispute
    assert out["t4"] == pytest.approx(1 / 3)  # history {t1, t2, t3}


def test_a_row_never_sees_its_own_outcome(frame):
    """
    t4 is itself disputed. Its own chargeback is filed seven weeks later and
    must not move its own feature value -- that is the leak notebook 01 had.
    """
    with_outcome = strict(frame)
    without = frame.copy()
    without.loc["t4", "chargeback_filed_at"] = pd.NaT
    pd.testing.assert_series_equal(with_outcome, strict(without))
    assert with_outcome["t4"] == pytest.approx(1 / 3)


def test_the_future_never_changes_the_past(frame):
    """Dropping everything after t3 leaves t1..t3 exactly where they were."""
    full = strict(frame)
    truncated = frame[frame["timestamp"] <= frame.loc["t3", "timestamp"]].copy()
    truncated["chargeback_filed_at"] = truncated["chargeback_filed_at"].where(
        truncated["chargeback_filed_at"] <= frame.loc["t3", "timestamp"]
    )
    pd.testing.assert_series_equal(full.loc[truncated.index], strict(truncated))


def test_cards_are_isolated(frame):
    assert strict(frame)["t5"] == 0.0


def test_no_history_is_zero_not_nan(frame):
    out = strict(frame)
    assert out["t1"] == 0.0
    assert not out.isna().any()
    assert np.isfinite(out.to_numpy()).all()


def test_scalar_as_of_applies_one_cutoff_to_every_row(frame):
    out = card_chargeback_rate(frame, "2026-03-01T00:00:00Z")
    # Card A as of Mar 1: two prior transactions, one filed dispute.
    assert out.loc[["t1", "t2", "t3", "t4"]].tolist() == pytest.approx([0.5] * 4)
    assert out["t5"] == 0.0


def test_nightly_batch_cutoff_excludes_same_day_history(frame):
    """
    t4 is at 12:00 on Mar 1. A nightly batch served history as of 00:00, so
    t3 (also Mar 1) is not yet in the denominator.
    """
    out = card_chargeback_rate(frame, nightly_batch_as_of(frame))
    assert out["t4"] == pytest.approx(1 / 2)
    assert out["t3"] == pytest.approx(1 / 2)


def test_mixed_timestamp_resolutions_are_tolerated(frame):
    """Parquet round-trips leave timestamp in us and chargeback_filed_at in ns."""
    mixed = frame.copy()
    mixed["timestamp"] = mixed["timestamp"].astype("datetime64[us, UTC]")
    mixed["chargeback_filed_at"] = mixed["chargeback_filed_at"].astype("datetime64[ns, UTC]")
    pd.testing.assert_series_equal(strict(mixed), strict(frame))


def test_frame_with_no_chargebacks_at_all(frame):
    frame["chargeback_filed_at"] = pd.NaT
    assert strict(frame).tolist() == [0.0] * 5


def test_rejects_a_chargeback_filed_before_its_transaction(frame):
    frame.loc["t1", "chargeback_filed_at"] = pd.Timestamp("2025-12-31T00:00:00Z")
    with pytest.raises(ValueError, match="precedes"):
        strict(frame)


def test_rejects_a_misaligned_per_row_cutoff(frame):
    with pytest.raises(ValueError, match="aligned"):
        card_chargeback_rate(frame, frame["timestamp"].iloc[:3])


def test_rejects_nat_cutoffs(frame):
    as_of = frame["timestamp"].copy()
    as_of["t2"] = pd.NaT
    with pytest.raises(ValueError, match="NaT"):
        card_chargeback_rate(frame, as_of)


def test_the_notebook_definition_is_not_this_definition(frame):
    """
    Notebook 01's per-card rate over the whole table gives t1 a value of 0.5
    before either dispute exists. The point-in-time value is 0.0. This test is
    here so the difference is visible next to the implementation.
    """
    full_table = frame["card_token"].map(
        frame.groupby("card_token")["chargeback_filed_at"].apply(lambda s: s.notna().mean())
    )
    assert full_table["t1"] == pytest.approx(0.5)
    assert strict(frame)["t1"] == 0.0


def test_build_returns_every_aggregate(frame):
    out = build(frame, frame["timestamp"])
    assert set(out.columns) == set(AGGREGATE_FEATURES)
    assert out.index.equals(frame.index)
