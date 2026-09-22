"""
Gate 2 -- performance floor on a temporal split.

    python -m ml.validation.performance --min-pr-auc 0.15

Trains the registered feature set on the first 70% of the window and scores
the last 30%, then fails if holdout PR-AUC is below the floor. The split is
temporal because fraud is non-stationary and a random split flatters
everything.

Why PR-AUC and not AUC: at ~3.5% positives, AUC is dominated by how the easy
negatives are ordered. PR-AUC and recall at the review budget describe what
the review queue will actually see.

The report also carries:

* recall and precision at the operating point (the top ``REVIEW_BUDGET`` of
  training scores go to manual review), because a floor on a ranking metric
  says nothing about the queue;
* holdout metrics by calendar month -- a model that only works on average is
  a model that stopped working in month three;
* the champion feature set on the identical split, so "clears the floor" is
  never confused with "beats production".

Gate 2 trusts Gate 1. A leaked feature clears any floor -- the test suite runs
the notebook-01 definition of ``card_chargeback_rate`` through this gate to
show exactly that, which is why the workflow runs the leakage gate first.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from ml.fraud import pipeline
from ml.validation import common


@dataclass(frozen=True)
class Metrics:
    """Ranking metrics plus the operating-point metrics at a fixed threshold."""

    label: str
    n: int
    positives: int
    auc: float
    pr_auc: float
    flag_rate: float
    recall: float
    precision: float
    fpr: float

    def as_row(self) -> dict[str, object]:
        return {
            "slice": self.label,
            "n": self.n,
            "fraud": self.positives,
            "fraud rate": self.positives / self.n if self.n else float("nan"),
            "AUC": self.auc,
            "PR-AUC": self.pr_auc,
            "flag rate": self.flag_rate,
            "recall": self.recall,
            "precision": self.precision,
            "FPR": self.fpr,
        }


def metrics(label: str, y: np.ndarray, scores: np.ndarray, threshold: float) -> Metrics:
    """
    Metrics for one population. ``threshold`` is the operating point; rows
    scoring at or above it are flagged. Undefined quantities are NaN, never
    zero -- a slice with no fraud has no recall, and saying 0.0 would read as
    "misses everything".
    """
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    if y.shape != scores.shape:
        raise ValueError(f"{label}: {y.shape} labels for {scores.shape} scores")
    flagged = scores >= threshold
    positives = int(y.sum())
    negatives = int(y.size - positives)
    has_both = 0 < positives < y.size
    return Metrics(
        label=label,
        n=int(y.size),
        positives=positives,
        auc=float(roc_auc_score(y, scores)) if has_both else float("nan"),
        pr_auc=float(average_precision_score(y, scores)) if has_both else float("nan"),
        flag_rate=float(flagged.mean()) if y.size else float("nan"),
        recall=float(flagged[y == 1].mean()) if positives else float("nan"),
        precision=float(y[flagged].mean()) if flagged.any() else float("nan"),
        fpr=float(flagged[y == 0].mean()) if negatives else float("nan"),
    )


@dataclass
class PerformanceReport:
    columns: tuple[str, ...]
    split_cutoff: pd.Timestamp
    holdout_window: tuple[pd.Timestamp, pd.Timestamp]
    budget: float
    threshold: float
    overall: Metrics
    by_month: list[Metrics]
    champion: Metrics | None
    min_pr_auc: float | None
    min_auc: float | None

    @property
    def failures(self) -> list[str]:
        out: list[str] = []
        if self.min_pr_auc is not None and not self.overall.pr_auc >= self.min_pr_auc:
            out.append(f"PR-AUC {common.fmt(self.overall.pr_auc)} < floor {self.min_pr_auc}")
        if self.min_auc is not None and not self.overall.auc >= self.min_auc:
            out.append(f"AUC {common.fmt(self.overall.auc)} < floor {self.min_auc}")
        return out

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def advisories(self) -> list[str]:
        out: list[str] = []
        if self.champion is not None:
            if self.overall.pr_auc <= self.champion.pr_auc:
                out.append(
                    f"candidate does not beat the champion on PR-AUC "
                    f"({common.fmt(self.overall.pr_auc)} vs {common.fmt(self.champion.pr_auc)}) -- "
                    "clearing the floor is not a reason to promote"
                )
            if self.overall.auc <= self.champion.auc:
                out.append(
                    f"candidate does not beat the champion on AUC "
                    f"({common.fmt(self.overall.auc)} vs {common.fmt(self.champion.auc)})"
                )
        worst = min(self.by_month, key=lambda m: m.pr_auc if np.isfinite(m.pr_auc) else np.inf, default=None)
        if worst is not None and self.min_pr_auc is not None and worst.pr_auc < self.min_pr_auc:
            out.append(f"month {worst.label} is below the floor on its own (PR-AUC {common.fmt(worst.pr_auc)})")
        return out

    def render(self) -> str:
        columns = ["slice", "n", "fraud", "AUC", "PR-AUC", "flag rate", "recall", "precision"]
        start, end = self.holdout_window
        parts = [
            "# Gate 2 -- performance floor (temporal split)",
            "",
            f"features: {', '.join(self.columns)}",
            f"split: rows up to {self.split_cutoff:%Y-%m-%d %H:%M} train; "
            f"holdout n={self.overall.n:,} ({start:%Y-%m-%d} -> {end:%Y-%m-%d})",
            f"operating point: top {self.budget:.1%} of training scores -> threshold {self.threshold:.4f}",
            "",
            common.markdown_table(
                (m.as_row() for m in [self.overall, *self.by_month, *([self.champion] if self.champion else [])]),
                columns,
            ),
            "",
        ]
        if self.advisories:
            parts += ["## Advisories", ""] + [f"- {line}" for line in self.advisories] + [""]
        floors = [f"PR-AUC >= {self.min_pr_auc}" if self.min_pr_auc is not None else None,
                  f"AUC >= {self.min_auc}" if self.min_auc is not None else None]
        floors = [f for f in floors if f]
        parts.append("floor: " + (", ".join(floors) if floors else "none (report only)"))
        if self.ok:
            parts.append(f"RESULT: PASS (PR-AUC {common.fmt(self.overall.pr_auc)}, AUC {common.fmt(self.overall.auc)})")
        else:
            parts.append("RESULT: FAIL -- " + "; ".join(self.failures))
        return "\n".join(parts)


def evaluate(
    df: pd.DataFrame,
    columns: Sequence[str] = pipeline.CANDIDATE_FEATURES,
    *,
    fraction: float = pipeline.SPLIT_FRACTION,
    budget: float = pipeline.REVIEW_BUDGET,
    X: pd.DataFrame | None = None,
    champion_columns: Sequence[str] | None = pipeline.CHAMPION_FEATURES,
    min_pr_auc: float | None = None,
    min_auc: float | None = None,
) -> PerformanceReport:
    """
    Train ``columns`` on the temporal split and measure the holdout.

    ``X`` lets a caller evaluate a feature frame built elsewhere through the
    same model and split; the tests use it to push the leaky notebook
    definition through this gate. The champion is always built from ``df``
    by the pipeline, so the comparison row is never contaminated by ``X``.
    """
    columns = tuple(columns)
    trained = pipeline.train(df, columns, fraction, X=X)
    threshold = pipeline.review_threshold(trained.train_scores, budget)
    y = trained.y_test.to_numpy()
    scores = trained.test_scores
    holdout_ts = df.loc[trained.split.test, "timestamp"]
    months = common.month_of(holdout_ts).to_numpy()

    overall = metrics("holdout", y, scores, threshold)
    by_month = [metrics(month, y[months == month], scores[months == month], threshold) for month in sorted(set(months))]

    champion: Metrics | None = None
    if champion_columns is not None and tuple(champion_columns) != columns:
        ch = pipeline.train(df, champion_columns, fraction)
        champion = metrics(
            "champion (same split)",
            ch.y_test.to_numpy(),
            ch.test_scores,
            pipeline.review_threshold(ch.train_scores, budget),
        )

    return PerformanceReport(
        columns=columns,
        split_cutoff=trained.split.cutoff,
        holdout_window=(holdout_ts.min(), holdout_ts.max()),
        budget=budget,
        threshold=threshold,
        overall=overall,
        by_month=by_month,
        champion=champion,
        min_pr_auc=min_pr_auc,
        min_auc=min_auc,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    df: pd.DataFrame | None = None,
    X: pd.DataFrame | None = None,
    out=None,
) -> int:
    parser = argparse.ArgumentParser(description="Gate 2 -- performance floor on a temporal split")
    parser.add_argument("--min-pr-auc", type=float, default=None, help="fail if holdout PR-AUC is below this")
    parser.add_argument("--min-auc", type=float, default=None, help="optionally also floor the AUC")
    parser.add_argument("--budget", type=float, default=pipeline.REVIEW_BUDGET, help="share of traffic sent to review")
    common.add_data_arguments(parser)
    args = parser.parse_args(argv)
    out = out or sys.stdout

    df = common.load(args) if df is None else df
    report = evaluate(
        df,
        common.feature_columns(args),
        fraction=args.split,
        budget=args.budget,
        X=X,
        min_pr_auc=args.min_pr_auc,
        min_auc=args.min_auc,
    )
    print(report.render(), file=out)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
