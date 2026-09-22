"""
Production fraud pipeline: transactions -> features -> temporal split -> model.

This is the one place that says what the fraud model is: which features it
takes, how each one is computed at serving time, how the training table is
split, and how the review threshold is set. The validation gates in
ml/validation/ import from here so that what they validate is what ships.

Two rules are enforced structurally rather than by convention:

* The label never reaches a feature function. ``observable_frame`` strips
  ``is_fraud`` before features are built; a feature that reads it raises.
* Historical aggregates are computed with the cutoff the serving path
  actually has. ``card_chargeback_rate`` is computed as of each transaction's
  own timestamp (``aggregates.scoring_time_as_of``) -- the cutoff under which
  the shadow run's feature stats and metrics reproduce exactly -- and never
  as of the whole table. ``serving_cutoff`` is the single place to change if
  platform confirms the ``card_history`` batch is served a day stale.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from ml.features import aggregates, base

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "ml" / "data" / "transactions.parquet"

LABEL = "is_fraud"
#: Columns that describe an outcome. Never passed to a feature function.
OUTCOME_COLUMNS = (LABEL,)

#: Temporal split: the first 70% of the window trains, the last 30% holds out.
SPLIT_FRACTION = 0.70
#: Operating point: the top 5% of scores go to manual review.
REVIEW_BUDGET = 0.05

#: fraud-v2, the champion. Six observable-at-authorization features.
CHAMPION_FEATURES: tuple[str, ...] = tuple(base.BASE_FEATURES)
#: fraud-v3, the candidate: champion features plus a point-in-time card history aggregate.
CANDIDATE_FEATURES: tuple[str, ...] = CHAMPION_FEATURES + tuple(aggregates.AGGREGATE_FEATURES)

MODEL_PARAMS: dict[str, object] = {"max_iter": 250, "random_state": 0}

FeatureFn = Callable[[pd.DataFrame], pd.Series]


def load_transactions(path: Path = DATA_PATH) -> pd.DataFrame:
    """Synthetic transactions, time-ordered with a clean integer index."""
    df = pd.read_parquet(path)
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)


def observable_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Everything a feature is allowed to see. The label is not in it."""
    return df.drop(columns=list(OUTCOME_COLUMNS), errors="ignore")


def serving_cutoff(df: pd.DataFrame) -> pd.Series:
    """
    Per-row ``as_of`` matching what the serving path computes.

    The shadow run's ``card_chargeback_rate`` stats (non-zero share 0.1419)
    reproduce under the scoring-timestamp cutoff and not under a midnight one
    (0.1411), so that is the cutoff training uses. Swap in
    ``aggregates.nightly_batch_as_of`` if the batch is confirmed to be a day
    stale; on this data the two differ by 0.0005 AUC.
    """
    return aggregates.scoring_time_as_of(df)


def feature_functions() -> dict[str, FeatureFn]:
    """
    Every feature the pipeline knows how to compute, as ``frame -> Series``.

    Aggregates are bound to the serving cutoff here, so callers (and the
    leakage gate) see one uniform signature and cannot forget the ``as_of``.
    """
    fns: dict[str, FeatureFn] = dict(base.BASE_FEATURES)
    for name, fn in aggregates.AGGREGATE_FEATURES.items():
        fns[name] = _bind_cutoff(fn)
    return fns


def _bind_cutoff(fn: Callable[[pd.DataFrame, pd.Series], pd.Series]) -> FeatureFn:
    return lambda frame: fn(frame, serving_cutoff(frame))


def build_features(df: pd.DataFrame, columns: Sequence[str] = CANDIDATE_FEATURES) -> pd.DataFrame:
    """
    Feature frame for ``columns``, computed over the whole of ``df``.

    Compute on the full table *then* split: the point-in-time aggregates for
    the holdout need the training window's history, and they only ever look
    backwards from each row's own cutoff.
    """
    obs = observable_frame(df)
    fns = feature_functions()
    return pd.DataFrame({name: fns[name](obs) for name in columns}, index=df.index)


@dataclass(frozen=True)
class Split:
    cutoff: pd.Timestamp
    train: pd.Index
    test: pd.Index


def temporal_split(df: pd.DataFrame, fraction: float = SPLIT_FRACTION) -> Split:
    """Rows at or before the ``fraction`` quantile of time train; the rest hold out."""
    cutoff = df["timestamp"].quantile(fraction)
    is_train = df["timestamp"] <= cutoff
    return Split(cutoff=cutoff, train=df.index[is_train], test=df.index[~is_train])


def fit(X: pd.DataFrame, y: pd.Series) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(**MODEL_PARAMS).fit(X, y)


def review_threshold(scores: np.ndarray, budget: float = REVIEW_BUDGET) -> float:
    """Score above which a transaction is flagged, at the given review budget."""
    return float(np.quantile(scores, 1.0 - budget))


@dataclass
class Trained:
    """A fitted model plus everything the gates need to evaluate it."""

    columns: tuple[str, ...]
    split: Split
    X: pd.DataFrame
    y: pd.Series
    model: HistGradientBoostingClassifier
    train_scores: np.ndarray
    test_scores: np.ndarray

    @property
    def y_test(self) -> pd.Series:
        return self.y.loc[self.split.test]

    @property
    def y_train(self) -> pd.Series:
        return self.y.loc[self.split.train]


def train(
    df: pd.DataFrame,
    columns: Sequence[str] = CANDIDATE_FEATURES,
    fraction: float = SPLIT_FRACTION,
    X: pd.DataFrame | None = None,
) -> Trained:
    """
    Build features, split temporally, fit, score both halves.

    ``X`` may be supplied to evaluate a feature frame built elsewhere (the
    validation tests use this to run a deliberately leaky definition through
    the same model and split).
    """
    columns = tuple(columns)
    X = build_features(df, columns) if X is None else X.loc[:, list(columns)]
    y = df[LABEL]
    split = temporal_split(df, fraction)
    model = fit(X.loc[split.train], y.loc[split.train])
    return Trained(
        columns=columns,
        split=split,
        X=X,
        y=y,
        model=model,
        train_scores=model.predict_proba(X.loc[split.train])[:, 1],
        test_scores=model.predict_proba(X.loc[split.test])[:, 1],
    )
