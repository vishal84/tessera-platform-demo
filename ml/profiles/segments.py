"""
Customer behaviour profiles.

Behavioural segmentation over transaction history, used by product for
targeting and by risk as a context signal (a transaction that is normal for a
"high-frequency commuter" is abnormal for a "monthly bulk shopper").

Status: scaffolding. The segmentation runs, but it has the same problems the
fraud notebook had before it was productionised -- no point-in-time
discipline, no tests, no drift monitoring. It is scheduled to move onto the
same rails as ml/features/ next quarter.

The point-in-time rule applies here too, and is easy to miss: a profile
attached to a transaction must be built from behaviour *before* that
transaction. A segment computed over a customer's full history and then joined
onto their earlier transactions leaks the future into the past.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEGMENTS = {
    0: "low-frequency low-value",
    1: "high-frequency commuter",
    2: "monthly bulk shopper",
    3: "cross-border frequent",
    4: "nocturnal / irregular",
}


def behavioural_summary(transactions: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """
    Per-card behavioural summary using only transactions strictly before `as_of`.

    The `as_of` argument is not optional by accident. A summary without a
    cutoff is a leak waiting to happen.
    """
    history = transactions[transactions["timestamp"] < as_of]
    if history.empty:
        return pd.DataFrame(
            columns=["txn_count", "mean_amount", "night_share", "cross_border_share", "distinct_mcc"]
        )

    grouped = history.groupby("card_token")
    return pd.DataFrame(
        {
            "txn_count": grouped.size(),
            "mean_amount": grouped["amount_minor"].mean(),
            "night_share": grouped["timestamp"].apply(
                lambda s: ((s.dt.hour >= 1) & (s.dt.hour <= 5)).mean()
            ),
            "cross_border_share": grouped["is_cross_border"].mean(),
            "distinct_mcc": grouped["mcc"].nunique(),
        }
    )


def assign_segments(summary: pd.DataFrame, n_segments: int = 5, seed: int = 0) -> pd.Series:
    """K-means over the behavioural summary. Deterministic given a seed."""
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    if summary.empty:
        return pd.Series(dtype="int64")

    scaled = StandardScaler().fit_transform(summary.fillna(0.0))
    labels = KMeans(n_clusters=n_segments, random_state=seed, n_init=10).fit_predict(scaled)
    return pd.Series(labels, index=summary.index, name="segment")
