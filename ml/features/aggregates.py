"""
Point-in-time historical aggregates for the fraud model.

Every function here takes an explicit ``as_of`` cutoff and only looks at
history that existed *strictly before* it. That is the whole design: a
historical aggregate without a cutoff is the single most common way a fraud
model ends up reading its own label.

Why this matters for chargebacks specifically
--------------------------------------------
A chargeback is filed 20-90 days after the transaction it disputes (median 54
days in our data). The training table has ``chargeback_filed_at`` filled in
for every row, so a per-card chargeback rate computed over the whole table
tells the model, for the row being scored, whether *that row* was eventually
disputed. Notebook 01 did exactly that and reported 0.906 AUC; scored
point-in-time in shadow the same model did 0.699. See
ml/notebooks/03_v3_shadow_investigation.ipynb for the numbers.

The ``as_of`` argument
----------------------
``as_of`` is either a single timestamp (one cutoff for every row -- useful
for backfills and for the ``segments.py`` style of profile) or a Series
aligned with ``df`` giving a per-row cutoff. For training tables the per-row
form is the one you want, and it has to be the cutoff the serving path
really has:

* ``scoring_time_as_of(df)`` -- each transaction's own timestamp. This is
  what the shadow run served: its reported feature stats (non-zero share
  0.1419) and all four of its metrics reproduce under this cutoff and not
  under the next one. ``ml/fraud/pipeline.py`` uses it.
* ``nightly_batch_as_of(df)`` -- 00:00 on the transaction's day, for a batch
  that is up to a day stale. Switch to it if platform confirms the batch is
  really served that way; on this data the two differ by 0.0005 AUC.

Both the numerator and the denominator respect the cutoff. A chargeback is
counted only if it was *filed* before ``as_of``; a transaction is counted as
history only if it *happened* before ``as_of``. ``as_of`` itself is excluded
(strict inequality), so a row never sees itself.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

# Everything is compared in one resolution. Parquet round-trips can leave
# ``timestamp`` in microseconds and ``chargeback_filed_at`` in nanoseconds,
# and merge_asof refuses to compare the two.
_TIME_DTYPE = "datetime64[ns, UTC]"

REQUIRED_COLUMNS = ("card_token", "timestamp", "chargeback_filed_at")


def nightly_batch_as_of(df: pd.DataFrame) -> pd.Series:
    """
    The cutoff the ``card_history`` nightly batch effectively serves.

    The batch runs once a day, so a transaction at 14:00 is scored against
    history as of 00:00 that morning. Flooring each row's timestamp to the
    day reproduces that staleness in the training table instead of pretending
    the feature is fresh to the second.
    """
    return _to_utc(df["timestamp"]).dt.floor("D")


def scoring_time_as_of(df: pd.DataFrame) -> pd.Series:
    """
    The cutoff the shadow run's serving path actually used: each transaction's
    own timestamp. History strictly before the moment of scoring, nothing at
    or after it.
    """
    return _to_utc(df["timestamp"])


def card_history(df: pd.DataFrame, as_of: pd.Series | pd.Timestamp | str) -> pd.DataFrame:
    """
    Per row, the card's history as it stood at ``as_of``.

    prior_transactions  transactions on this card with ``timestamp < as_of``
    prior_chargebacks   chargebacks on this card with ``chargeback_filed_at < as_of``

    Both count things that had *happened* by the cutoff. A chargeback that
    has been filed counts even if the transaction it disputes is the most
    recent one; a chargeback that will be filed next month does not exist.
    The row itself is never in its own history (strict inequality).
    """
    _validate(df)
    cutoff = _as_of_series(df, as_of)
    return pd.DataFrame(
        {
            "prior_transactions": _count_before(df, cutoff, "timestamp"),
            "prior_chargebacks": _count_before(df, cutoff, "chargeback_filed_at"),
        },
        index=df.index,
    )


def card_chargeback_rate(df: pd.DataFrame, as_of: pd.Series | pd.Timestamp | str) -> pd.Series:
    """
    Share of a card's prior transactions that had a chargeback *filed* before ``as_of``.

    numerator   chargebacks on this card with ``chargeback_filed_at < as_of``
    denominator transactions on this card with ``timestamp < as_of``

    Rows with no prior history get 0.0, not NaN: "we know nothing about this
    card" and "this card has never been disputed" are the same thing to the
    model at scoring time, and the tree cannot split on NaN in a way that
    survives serving.

    ``as_of`` may be one timestamp for every row or a per-row Series aligned
    with ``df``.
    """
    history = card_history(df, as_of)
    prior = history["prior_transactions"]
    rate = history["prior_chargebacks"] / prior.where(prior > 0)
    return rate.fillna(0.0).rename("card_chargeback_rate")


AGGREGATE_FEATURES: dict[str, Callable[[pd.DataFrame, pd.Series | pd.Timestamp | str], pd.Series]] = {
    "card_chargeback_rate": card_chargeback_rate,
}


def build(df: pd.DataFrame, as_of: pd.Series | pd.Timestamp | str) -> pd.DataFrame:
    """Assemble every aggregate feature at the given cutoff."""
    return pd.DataFrame({name: fn(df, as_of) for name, fn in AGGREGATE_FEATURES.items()}, index=df.index)


# --- internals ----------------------------------------------------------------


def _to_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True).astype(_TIME_DTYPE)


def _validate(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(f"aggregates need columns {missing}")
    filed = _to_utc(df["chargeback_filed_at"])
    happened = _to_utc(df["timestamp"])
    if (filed < happened).any():
        # A dispute cannot precede the transaction it disputes. If one does,
        # the data is wrong and the cutoff logic below would silently count it.
        raise ValueError("chargeback_filed_at precedes timestamp on at least one row")


def _as_of_series(df: pd.DataFrame, as_of: pd.Series | pd.Timestamp | str) -> pd.Series:
    if isinstance(as_of, pd.Series):
        if len(as_of) != len(df) or not as_of.index.equals(df.index):
            raise ValueError("per-row as_of must be aligned with df")
        cutoff = _to_utc(as_of)
    else:
        cutoff = pd.Series(pd.Timestamp(as_of), index=df.index)
        cutoff = _to_utc(cutoff)
    if cutoff.isna().any():
        raise ValueError("as_of contains NaT")
    return cutoff


def _count_before(df: pd.DataFrame, cutoff: pd.Series, event_col: str) -> pd.Series:
    """
    For each row: how many rows on the same card have ``event_col`` strictly
    before that row's cutoff. Vectorised with merge_asof on a per-card running
    count, so it is O(n log n) rather than a Python loop over cards.
    """
    queries = pd.DataFrame(
        {
            "card_token": df["card_token"].to_numpy(),
            "as_of": cutoff.to_numpy(),
            "_row": np.arange(len(df)),
        }
    ).sort_values("as_of", kind="stable")

    has_event = df[event_col].notna().to_numpy()
    counts = np.zeros(len(df), dtype=float)
    if not has_event.any():
        return pd.Series(counts, index=df.index)

    events = pd.DataFrame(
        {
            "card_token": df["card_token"].to_numpy()[has_event],
            "event_at": _to_utc(df[event_col]).to_numpy()[has_event],
        }
    ).sort_values("event_at", kind="stable")
    events["_running"] = events.groupby("card_token").cumcount() + 1

    merged = pd.merge_asof(
        queries,
        events,
        left_on="as_of",
        right_on="event_at",
        by="card_token",
        allow_exact_matches=False,  # strictly before: a row never counts itself
        direction="backward",
    )
    counts[merged["_row"].to_numpy()] = merged["_running"].fillna(0).to_numpy()
    return pd.Series(counts, index=df.index)
