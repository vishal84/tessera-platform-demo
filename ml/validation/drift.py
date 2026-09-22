"""
Gate 3 -- drift between the training distribution and recent traffic.

    python -m ml.validation.drift --max-psi 0.25

Population stability index (PSI) per feature between the training window and
the most recent window we have. By default "recent" is the holdout window,
which for this repo is also the shadow window -- the closest thing to recent
production traffic that exists here. ``--recent-days N`` narrows it to the
last N days of the table.

The score the model produces is checked too. Label feedback arrives 20-90
days late, so a shift in the score distribution is the earliest alarm there
is; accuracy is the last.

Binning matters more than the formula
-------------------------------------
The usual PSI recipe -- ten quantile bins on the training distribution --
is blind to exactly the feature this gate exists for. ``card_chargeback_rate``
is zero for 97% of training rows, so every quantile edge lands on zero and
the ten bins collapse to one. PSI over one bin is identically zero, and a
feature whose non-zero share quadruples is reported as perfectly stable.

So any value carrying at least ``MASS_POINT_SHARE`` of the pooled sample gets
its own bin, and quantile bins are drawn over what is left. A binary feature
becomes two bins; a zero-inflated rate becomes {0} plus quantile bins over the
non-zero values. The bin count is reported so the reader can see what was
compared.

Conventions: below ``WARN_PSI`` stable, ``WARN_PSI`` to ``--max-psi``
investigate (reported as a warning, not a failure), above ``--max-psi`` fail.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.fraud import pipeline
from ml.validation import common

BINS = 10
MASS_POINT_SHARE = 0.05
WARN_PSI = 0.10
EPS = 1e-6
SCORE_ROW = "model score"


@dataclass(frozen=True)
class Psi:
    value: float
    n_bins: int
    mass_points: tuple[float, ...]


def _bins(expected: np.ndarray, actual: np.ndarray, bins: int, mass_point_share: float) -> tuple[np.ndarray, np.ndarray]:
    pooled = np.concatenate([expected, actual])
    values, counts = np.unique(pooled, return_counts=True)
    mass = values[counts / pooled.size >= mass_point_share]
    rest = pooled[~np.isin(pooled, mass)]
    edges = np.unique(np.quantile(rest, np.linspace(0.0, 1.0, bins + 1))) if rest.size else np.array([])
    return mass, edges


def _shares(sample: np.ndarray, mass: np.ndarray, edges: np.ndarray) -> np.ndarray:
    counts = [float(np.sum(sample == point)) for point in mass]
    rest = sample[~np.isin(sample, mass)]
    if edges.size >= 2:
        open_edges = edges.astype(float).copy()
        open_edges[0], open_edges[-1] = -np.inf, np.inf
        counts.extend(np.histogram(rest, open_edges)[0].astype(float))
    elif edges.size == 1:
        counts.append(float(rest.size))
    return np.asarray(counts, dtype=float) / sample.size


def psi(
    expected: Sequence[float] | np.ndarray | pd.Series,
    actual: Sequence[float] | np.ndarray | pd.Series,
    *,
    bins: int = BINS,
    mass_point_share: float = MASS_POINT_SHARE,
    eps: float = EPS,
) -> Psi:
    """
    PSI of ``actual`` against ``expected`` with mass-point-aware binning.

    Bins are decided on the pooled sample so both sides are cut the same way;
    empty bins are floored at ``eps`` so the log is finite. NaNs are dropped
    from both sides -- a feature that is finite by construction has none, and
    a feature that does not is a different bug.
    """
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    expected = expected[~np.isnan(expected)]
    actual = actual[~np.isnan(actual)]
    if expected.size == 0 or actual.size == 0:
        raise ValueError("psi needs a non-empty sample on both sides")
    mass, edges = _bins(expected, actual, bins, mass_point_share)
    e = np.clip(_shares(expected, mass, edges), eps, None)
    a = np.clip(_shares(actual, mass, edges), eps, None)
    return Psi(float(np.sum((a - e) * np.log(a / e))), int(e.size), tuple(float(m) for m in mass))


@dataclass(frozen=True)
class DriftRow:
    name: str
    psi: Psi
    train_mean: float
    recent_mean: float
    train_nonzero: float
    recent_nonzero: float

    def status(self, warn_psi: float, max_psi: float | None) -> str:
        if max_psi is not None and self.psi.value > max_psi:
            return "FAIL"
        if self.psi.value >= warn_psi:
            return "warn"
        return "ok"

    def as_row(self, warn_psi: float, max_psi: float | None) -> dict[str, object]:
        return {
            "feature": self.name,
            "PSI": self.psi.value,
            "bins": self.psi.n_bins,
            "mean (train)": self.train_mean,
            "mean (recent)": self.recent_mean,
            "non-zero (train)": self.train_nonzero,
            "non-zero (recent)": self.recent_nonzero,
            "result": self.status(warn_psi, max_psi),
        }


@dataclass
class DriftReport:
    rows: list[DriftRow]
    train_window: tuple[pd.Timestamp, pd.Timestamp]
    recent_window: tuple[pd.Timestamp, pd.Timestamp]
    n_train: int
    n_recent: int
    warn_psi: float
    max_psi: float | None

    @property
    def failing(self) -> list[str]:
        return [r.name for r in self.rows if r.status(self.warn_psi, self.max_psi) == "FAIL"]

    @property
    def warning(self) -> list[str]:
        return [r.name for r in self.rows if r.status(self.warn_psi, self.max_psi) == "warn"]

    @property
    def ok(self) -> bool:
        return not self.failing

    def row(self, name: str) -> DriftRow:
        return next(r for r in self.rows if r.name == name)

    def render(self) -> str:
        columns = ["feature", "PSI", "bins", "mean (train)", "mean (recent)", "non-zero (train)", "non-zero (recent)", "result"]
        t0, t1 = self.train_window
        r0, r1 = self.recent_window
        parts = [
            "# Gate 3 -- drift (training window vs recent traffic)",
            "",
            f"train : {t0:%Y-%m-%d} -> {t1:%Y-%m-%d}  n={self.n_train:,}",
            f"recent: {r0:%Y-%m-%d} -> {r1:%Y-%m-%d}  n={self.n_recent:,}",
            f"thresholds: warn >= {self.warn_psi}, fail > {self.max_psi if self.max_psi is not None else 'n/a (report only)'}",
            "",
            common.markdown_table((r.as_row(self.warn_psi, self.max_psi) for r in self.rows), columns),
            "",
        ]
        if self.warning:
            parts.append(
                "warnings: " + ", ".join(self.warning) + " -- above the investigate threshold; "
                "the model card must say why before this ships"
            )
        if self.ok:
            parts.append("RESULT: PASS" + (" with warnings" if self.warning else ""))
        else:
            parts.append("RESULT: FAIL -- drift above limit in " + ", ".join(self.failing))
        return "\n".join(parts)


def evaluate(
    df: pd.DataFrame,
    columns: Sequence[str] = pipeline.CANDIDATE_FEATURES,
    *,
    fraction: float = pipeline.SPLIT_FRACTION,
    recent_days: int | None = None,
    warn_psi: float = WARN_PSI,
    max_psi: float | None = None,
    include_score: bool = True,
) -> DriftReport:
    """
    PSI per feature (and for the model score) between the training window
    and the recent window. ``recent_days`` restricts "recent" to the last N
    days of the table; otherwise it is everything after the split.
    """
    columns = tuple(columns)
    split = pipeline.temporal_split(df, fraction)
    X = pipeline.build_features(df, columns)
    train_idx = split.train
    recent_idx = split.test
    if recent_days is not None:
        since = df["timestamp"].max() - pd.Timedelta(days=recent_days)
        recent_idx = recent_idx[(df.loc[recent_idx, "timestamp"] > since).to_numpy()]
    if len(recent_idx) == 0:
        raise ValueError("no rows in the recent window")

    def row(name: str, train_values: np.ndarray, recent_values: np.ndarray) -> DriftRow:
        return DriftRow(
            name=name,
            psi=psi(train_values, recent_values),
            train_mean=float(np.mean(train_values)),
            recent_mean=float(np.mean(recent_values)),
            train_nonzero=float(np.mean(train_values != 0)),
            recent_nonzero=float(np.mean(recent_values != 0)),
        )

    rows = [row(c, X.loc[train_idx, c].to_numpy(dtype=float), X.loc[recent_idx, c].to_numpy(dtype=float)) for c in columns]
    if include_score:
        trained = pipeline.train(df, columns, fraction, X=X)
        recent_scores = trained.model.predict_proba(X.loc[recent_idx])[:, 1]
        rows.append(row(SCORE_ROW, trained.train_scores, recent_scores))

    ts = df["timestamp"]
    return DriftReport(
        rows=rows,
        train_window=(ts.loc[train_idx].min(), ts.loc[train_idx].max()),
        recent_window=(ts.loc[recent_idx].min(), ts.loc[recent_idx].max()),
        n_train=len(train_idx),
        n_recent=len(recent_idx),
        warn_psi=warn_psi,
        max_psi=max_psi,
    )


def main(argv: Sequence[str] | None = None, *, df: pd.DataFrame | None = None, out=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 3 -- drift between training and recent traffic")
    parser.add_argument("--max-psi", type=float, default=None, help="fail if any feature (or the score) exceeds this PSI")
    parser.add_argument("--warn-psi", type=float, default=WARN_PSI, help="report PSI at or above this as a warning")
    parser.add_argument("--recent-days", type=int, default=None, help="use only the last N days as the recent window")
    common.add_data_arguments(parser)
    args = parser.parse_args(argv)
    out = out or sys.stdout

    df = common.load(args) if df is None else df
    report = evaluate(
        df,
        common.feature_columns(args),
        fraction=args.split,
        recent_days=args.recent_days,
        warn_psi=args.warn_psi,
        max_psi=args.max_psi,
    )
    print(report.render(), file=out)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
