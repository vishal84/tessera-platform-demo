"""
The feature definition that reached shadow, kept as a negative fixture.

``notebook01_card_chargeback_rate`` is notebook 01, cell 8: one chargeback
rate per card, computed over the whole table, then mapped onto every row.
For a transaction on day D it counts disputes filed after D -- including the
dispute of D itself, filed 20-90 days later. It scored 0.906 AUC offline and
0.699 in shadow (ml/registry/shadow/fraud-v3-candidate.json, TESS-2310).

Gate 1 must fail on it. ``test_leakage.py`` proves that it does, on every
blocking probe. **Do not fix this file**; it is wrong on purpose, and the
test that depends on it being wrong is the one that protects the next model.

``notebook01_device_card_count`` is the other full-table aggregate from the
same notebook. It reads no outcome column, so it is not target leakage, but
it does count cards that will only use the device in the future. Gate 1
reports it as an advisory, which is the distinction the gate is built to make.
"""

from __future__ import annotations

import pandas as pd

from ml.fraud import pipeline
from ml.fraud.pipeline import FeatureFn


def notebook01_card_chargeback_rate(frame: pd.DataFrame) -> pd.Series:
    """Per-card share of transactions ever disputed, over the whole frame. Leaky by construction."""
    card_cb_rate = frame.groupby("card_token")["chargeback_filed_at"].apply(lambda s: s.notna().mean())
    return frame["card_token"].map(card_cb_rate).fillna(0.0).rename("card_chargeback_rate")


def notebook01_device_card_count(frame: pd.DataFrame) -> pd.Series:
    """Distinct cards per device over the whole frame. Not label leakage; still reads the future."""
    dev_counts = frame.groupby("device_id")["card_token"].nunique()
    return frame["device_id"].map(dev_counts).fillna(1).astype(float).rename("device_card_count")


def leaky_feature_functions() -> dict[str, FeatureFn]:
    """The production feature set with ``card_chargeback_rate`` swapped for the notebook definition."""
    fns = pipeline.feature_functions()
    fns["card_chargeback_rate"] = notebook01_card_chargeback_rate
    return {name: fns[name] for name in pipeline.CANDIDATE_FEATURES}


def leaky_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """A feature frame with the leaky column, for pushing through Gates 2-3 via ``X=``."""
    X = pipeline.build_features(df)
    X["card_chargeback_rate"] = notebook01_card_chargeback_rate(pipeline.observable_frame(df))
    return X
