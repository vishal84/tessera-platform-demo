"""
Gate 4 -- performance per slice, not in aggregate.

    python -m ml.validation.fairness --report fairness.md

There is no protected attribute in the transaction table and the model must
never take one as input. What a fraud model can do instead is encode one
through a proxy: where a card is used, what it buys, when, and for how much.
So the slices here are the proxies -- country, cross-border, merchant
category, amount band, time of day -- and the report exists so a disparity
is a number MRM has read rather than a surprise a customer finds.

For each slice: size, fraud rate, and the same metrics Gate 2 reports at the
same operating point (the top ``REVIEW_BUDGET`` of training scores). Two
ratios against the largest slice in each dimension:

* **FPR ratio** -- how much more often a legitimate transaction in this slice
  is flagged than one in the reference slice. This is the customer-facing
  number: a false positive is a declined or held payment.
* **flag-rate ratio** -- how much of the review queue this slice takes.

Ratios outside ``FOUR_FIFTHS`` (0.8 to 1.25, the four-fifths rule applied in
both directions) are marked ``review``. A disparity is not automatically a
finding -- cross-border traffic really does carry three times the fraud
rate -- but it must be explained in the model card, not discovered later.

The workflow runs this gate as a report: it writes ``--report`` and exits 0.
``--fail-on-disparity RATIO`` makes it blocking for teams that want it to be.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ml.fraud import pipeline
from ml.validation import common
from ml.validation.performance import Metrics, metrics

FOUR_FIFTHS = (0.8, 1.25)
MIN_SLICE_ROWS = 50

# Amount bands in minor units. Labels are the ranges themselves; there is no
# currency conversion anywhere in this module.
AMOUNT_EDGES = [0, 1_000, 5_000, 20_000, 100_000, np.inf]
AMOUNT_LABELS = ["<1,000", "1,000-4,999", "5,000-19,999", "20,000-99,999", ">=100,000"]
HOUR_EDGES = [-1, 5, 11, 17, 23]
HOUR_LABELS = ["00-05", "06-11", "12-17", "18-23"]


def _country(df: pd.DataFrame) -> pd.Series:
    return df["country"].astype(str)


def _cross_border(df: pd.DataFrame) -> pd.Series:
    return df["is_cross_border"].map({0: "domestic", 1: "cross-border"}).astype(str)


def _mcc(df: pd.DataFrame) -> pd.Series:
    return df["mcc"].astype(str)


def _amount_band(df: pd.DataFrame) -> pd.Series:
    return pd.cut(df["amount_minor"], AMOUNT_EDGES, labels=AMOUNT_LABELS, right=False).astype(str)


def _hour_band(df: pd.DataFrame) -> pd.Series:
    return pd.cut(df["timestamp"].dt.hour, HOUR_EDGES, labels=HOUR_LABELS).astype(str)


#: Dimension -> function giving each row's slice label. Adding a slice is one line.
SLICES: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "country": _country,
    "is_cross_border": _cross_border,
    "mcc": _mcc,
    "amount_band": _amount_band,
    "hour_band": _hour_band,
}


@dataclass(frozen=True)
class SliceMetrics:
    dimension: str
    metrics: Metrics
    reference: bool
    fpr_ratio: float
    flag_ratio: float

    @property
    def name(self) -> str:
        return self.metrics.label

    def note(self, max_ratio: float | None = None) -> str:
        notes: list[str] = []
        if self.reference:
            notes.append("reference")
        if self.metrics.n < MIN_SLICE_ROWS:
            notes.append(f"small slice (n<{MIN_SLICE_ROWS})")
        if not self.reference and self.disparate:
            notes.append(f"review (FPR ratio {common.fmt(self.fpr_ratio, 2)})")
        if max_ratio is not None and self.breaches(max_ratio):
            notes.append("FAIL")
        return "; ".join(notes)

    @property
    def disparate(self) -> bool:
        low, high = FOUR_FIFTHS
        return bool(np.isfinite(self.fpr_ratio) and not low <= self.fpr_ratio <= high)

    def breaches(self, max_ratio: float) -> bool:
        return bool(not self.reference and np.isfinite(self.fpr_ratio) and self.fpr_ratio > max_ratio)

    def as_row(self, max_ratio: float | None = None) -> dict[str, object]:
        row = self.metrics.as_row()
        row.update({"FPR ratio": self.fpr_ratio, "flag ratio": self.flag_ratio, "note": self.note(max_ratio)})
        return row


@dataclass
class FairnessReport:
    columns: tuple[str, ...]
    budget: float
    threshold: float
    overall: Metrics
    slices: list[SliceMetrics]
    max_ratio: float | None

    def dimension(self, name: str) -> list[SliceMetrics]:
        return [s for s in self.slices if s.dimension == name]

    @property
    def dimensions(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.slices:
            seen.setdefault(s.dimension, None)
        return list(seen)

    @property
    def flagged_for_review(self) -> list[SliceMetrics]:
        return [s for s in self.slices if s.disparate and not s.reference]

    @property
    def failing(self) -> list[SliceMetrics]:
        if self.max_ratio is None:
            return []
        return [s for s in self.slices if s.breaches(self.max_ratio)]

    @property
    def ok(self) -> bool:
        return not self.failing

    def render(self) -> str:
        columns = ["slice", "n", "fraud rate", "AUC", "PR-AUC", "flag rate", "recall", "FPR", "precision", "FPR ratio", "flag ratio", "note"]
        parts = [
            "# Gate 4 -- fairness slices",
            "",
            f"features: {', '.join(self.columns)}",
            f"operating point: top {self.budget:.1%} of training scores -> threshold {self.threshold:.4f}",
            f"holdout: n={self.overall.n:,}, fraud rate {self.overall.positives / self.overall.n:.2%}, "
            f"flag rate {self.overall.flag_rate:.2%}, recall {self.overall.recall:.3f}, FPR {self.overall.fpr:.4f}",
            "",
            "Ratios are against the largest slice in each dimension. `review` marks an FPR ratio outside "
            f"{FOUR_FIFTHS[0]}-{FOUR_FIFTHS[1]}; it means the model card has to explain the number, "
            "not that the number is wrong.",
            "",
            "No protected attribute exists in this data. Every dimension below is a proxy: `country` and "
            "`is_cross_border` are the same column in the generator, so their two tables are identical by construction.",
            "",
        ]
        for dim in self.dimensions:
            parts += [f"## {dim}", "", common.markdown_table((s.as_row(self.max_ratio) for s in self.dimension(dim)), columns), ""]
        review = self.flagged_for_review
        if review:
            parts += ["## Flagged for review", ""]
            parts += [
                f"- {s.dimension}={s.name}: FPR {common.fmt(s.metrics.fpr)} vs reference, ratio {common.fmt(s.fpr_ratio, 2)}; "
                f"takes {s.metrics.flag_rate:.1%} of its own traffic into review"
                for s in review
            ]
            parts.append("")
        if self.ok:
            parts.append("RESULT: PASS (report written; " + f"{len(review)} slice(s) marked for review)")
        else:
            parts.append(
                f"RESULT: FAIL -- FPR ratio above {self.max_ratio} in "
                + ", ".join(f"{s.dimension}={s.name}" for s in self.failing)
            )
        return "\n".join(parts)


def evaluate(
    df: pd.DataFrame,
    columns: Sequence[str] = pipeline.CANDIDATE_FEATURES,
    *,
    fraction: float = pipeline.SPLIT_FRACTION,
    budget: float = pipeline.REVIEW_BUDGET,
    slices: dict[str, Callable[[pd.DataFrame], pd.Series]] | None = None,
    max_ratio: float | None = None,
) -> FairnessReport:
    """Train on the temporal split, then measure every slice of the holdout at one operating point."""
    columns = tuple(columns)
    slices = SLICES if slices is None else slices
    trained = pipeline.train(df, columns, fraction)
    threshold = pipeline.review_threshold(trained.train_scores, budget)
    holdout = df.loc[trained.split.test]
    y = trained.y_test.to_numpy()
    scores = trained.test_scores
    overall = metrics("holdout", y, scores, threshold)

    out: list[SliceMetrics] = []
    for dim, fn in slices.items():
        labels = fn(holdout).to_numpy()
        per_slice = {name: metrics(str(name), y[labels == name], scores[labels == name], threshold) for name in sorted(set(labels))}
        reference = max(per_slice.values(), key=lambda m: m.n)
        for name, m in per_slice.items():
            out.append(
                SliceMetrics(
                    dimension=dim,
                    metrics=m,
                    reference=m is reference,
                    fpr_ratio=_ratio(m.fpr, reference.fpr),
                    flag_ratio=_ratio(m.flag_rate, reference.flag_rate),
                )
            )
    return FairnessReport(columns, budget, threshold, overall, out, max_ratio)


def _ratio(value: float, reference: float) -> float:
    if not np.isfinite(value) or not np.isfinite(reference) or reference == 0:
        return float("nan")
    return float(value / reference)


def main(argv: Sequence[str] | None = None, *, df: pd.DataFrame | None = None, out=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 4 -- per-slice performance report")
    parser.add_argument("--report", type=Path, required=True, help="where to write the markdown report")
    parser.add_argument("--fail-on-disparity", type=float, default=None, metavar="RATIO",
                        help="exit 1 if any slice's FPR ratio exceeds RATIO (report-only otherwise)")
    parser.add_argument("--budget", type=float, default=pipeline.REVIEW_BUDGET, help="share of traffic sent to review")
    common.add_data_arguments(parser)
    args = parser.parse_args(argv)
    out = out or sys.stdout

    df = common.load(args) if df is None else df
    report = evaluate(df, common.feature_columns(args), fraction=args.split, budget=args.budget, max_ratio=args.fail_on_disparity)
    text = report.render()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text + "\n")
    print(text, file=out)
    print(f"\nwrote {args.report}", file=out)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
