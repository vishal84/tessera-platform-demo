"""
Observable-at-scoring-time features for the fraud model.

The rule this module exists to enforce: **a feature may only use information
that was available at the moment the transaction was scored.**

That sounds obvious and is violated constantly, because the training table has
every column filled in and nothing stops you using one. The usual casualty is
an aggregate built from `chargeback_filed_at` -- disputes arrive 20-90 days
after the transaction, so a chargeback rate computed over the whole table
tells the model the answer. See ml/features/aggregates.py for the
point-in-time implementations.

Everything here is a pure function of a single row's observable fields.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Merchant category codes, ranked by observed fraud exposure. This is a
# published network-level statistic, not something derived from our labels.
MCC_RISK_TIER = {
    5411: 1,  # grocery
    5812: 2,  # restaurants
    5999: 3,  # misc retail
    4789: 3,  # transport
    7995: 5,  # betting
    5967: 5,  # inbound telemarketing
    6011: 3,  # atm
    5732: 4,  # electronics
}


def amount_log(df: pd.DataFrame) -> pd.Series:
    """Log-scaled amount. Fraud amount distributions are heavily skewed."""
    return np.log1p(df["amount_minor"])


def hour_of_day(df: pd.DataFrame) -> pd.Series:
    return df["timestamp"].dt.hour


def is_night(df: pd.DataFrame) -> pd.Series:
    """01:00-05:00 local. Thin staffing, thin monitoring, high fraud rate."""
    hour = df["timestamp"].dt.hour
    return ((hour >= 1) & (hour <= 5)).astype(int)


def is_cross_border(df: pd.DataFrame) -> pd.Series:
    return df["is_cross_border"].astype(int)


def mcc_risk_tier(df: pd.DataFrame) -> pd.Series:
    return df["mcc"].map(MCC_RISK_TIER).fillna(3).astype(int)


def amount_zscore_within_mcc(df: pd.DataFrame) -> pd.Series:
    """
    How unusual this amount is for this merchant category.

    Uses only amount and MCC -- both known at authorization time -- so this is
    safe to compute over the whole frame.
    """
    logged = np.log1p(df["amount_minor"])
    grouped = logged.groupby(df["mcc"])
    return ((logged - grouped.transform("mean")) / grouped.transform("std")).fillna(0.0)


BASE_FEATURES = {
    "amount_log": amount_log,
    "hour_of_day": hour_of_day,
    "is_night": is_night,
    "is_cross_border": is_cross_border,
    "mcc_risk_tier": mcc_risk_tier,
    "amount_zscore_within_mcc": amount_zscore_within_mcc,
}


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Assemble the base feature frame."""
    return pd.DataFrame({name: fn(df) for name, fn in BASE_FEATURES.items()}, index=df.index)
