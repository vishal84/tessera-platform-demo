"""
Gate 1 -- point-in-time correctness.

    python -m ml.validation.leakage --fail-on-leak

The question this gate answers for every feature: **does its value for a
transaction change when information that did not yet exist at scoring time
is taken away?** If it does, the feature is reading the future, and every
performance number downstream of it is fiction.

It does not answer that question by inspecting code. It answers it
behaviourally, by recomputing the feature under three perturbations and
diffing the result:

``future outcomes hidden``  (blocking)
    Pick a cutoff T. Set ``chargeback_filed_at`` to NaT wherever the dispute
    was filed after T. For every transaction at or before T, the feature
    must be identical to what it was with the full table. This is the probe
    that catches the per-card chargeback rate from notebook 01: the rate for
    a card changes the moment a dispute filed after T is hidden.

``own outcome hidden``  (blocking)
    Take one disputed transaction and forget its dispute. That transaction's
    own feature values must not move -- a dispute is filed 20-90 days after
    the transaction it disputes, so at scoring time it did not exist. This
    is the most common leak of all, stated as directly as possible.

``future rows removed``  (advisory)
    Drop every transaction after T as well. A feature that changes here but
    passed the outcome probe is using frame-wide statistics over
    observable columns (a z-score against the whole table's mean, say). That
    is not target leakage, but it is a fit-before-split that should be frozen
    at training time, so it is reported as a warning rather than a failure.

Two structural checks run alongside:

* The label (``is_fraud``) is never in the frame a feature sees. A feature
  that reaches for it raises ``KeyError``, which this gate records as a leak.
* Advisory only: a single feature that alone ranks fraud above
  ``SUSPICIOUS_AUC`` on the holdout is printed with a warning. Leakage is
  the usual explanation for a feature that good; a genuinely great feature
  will survive the probes above and the warning is the reviewer's cue to
  read the model card.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ml.fraud import pipeline
from ml.fraud.pipeline import FeatureFn
from ml.validation import common

CUTOFF_QUANTILES: tuple[float, ...] = (0.25, 0.50, 0.75)
OWN_OUTCOME_SAMPLE = 20
SUSPICIOUS_AUC = 0.80
TOLERANCE = 1e-9

OUTCOME_TIME_COLUMN = "chargeback_filed_at"


@dataclass(frozen=True)
class ProbeResult:
    probe: str
    feature: str
    cutoff: str
    rows_compared: int
    rows_changed: int
    max_abs_change: float

    @property
    def changed(self) -> bool:
        return self.rows_changed > 0

    def as_row(self) -> dict[str, object]:
        return {
            "probe": self.probe,
            "feature": self.feature,
            "cutoff": self.cutoff,
            "rows compared": self.rows_compared,
            "rows changed": self.rows_changed,
            "max |change|": self.max_abs_change,
            "result": "LEAK" if self.changed else "ok",
        }


@dataclass
class LeakageReport:
    leaks: list[ProbeResult] = field(default_factory=list)
    warnings: list[ProbeResult] = field(default_factory=list)
    passed: list[ProbeResult] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.leaks

    @property
    def leaking_features(self) -> list[str]:
        return sorted({r.feature for r in self.leaks})

    def render(self) -> str:
        columns = ["probe", "feature", "cutoff", "rows compared", "rows changed", "max |change|", "result"]
        parts = ["# Gate 1 -- point-in-time correctness", ""]
        parts.append(common.markdown_table((r.as_row() for r in [*self.leaks, *self.passed]), columns, digits=6))
        if self.warnings:
            parts += ["", "## Warnings (not blocking): frame-wide statistics over observable columns", ""]
            warn_rows = ({**r.as_row(), "result": "warn"} for r in self.warnings)
            parts.append(common.markdown_table(warn_rows, columns, digits=6))
        if self.advisories:
            parts += ["", "## Advisories", ""]
            parts += [f"- {line}" for line in self.advisories]
        parts.append("")
        if self.ok:
            parts.append("RESULT: no leak detected")
        else:
            parts.append("RESULT: LEAK in " + ", ".join(self.leaking_features))
        return "\n".join(parts)


def run_probes(
    df: pd.DataFrame,
    features: Mapping[str, FeatureFn],
    *,
    cutoff_quantiles: Sequence[float] = CUTOFF_QUANTILES,
    own_outcome_sample: int = OWN_OUTCOME_SAMPLE,
    suspicious_auc: float = SUSPICIOUS_AUC,
) -> LeakageReport:
    """
    Run every probe over ``features`` and return the report.

    ``features`` maps a name to ``frame -> Series``; the frame passed in never
    contains the label. ``df`` is the full transaction table including
    outcomes, exactly as a training job would see it.
    """
    report = LeakageReport()
    obs = pipeline.observable_frame(df)
    baseline: dict[str, pd.Series] = {}

    for name, fn in features.items():
        try:
            baseline[name] = fn(obs)
        except KeyError as exc:
            # The label is deliberately absent. Reaching for it is a leak by definition.
            report.leaks.append(ProbeResult("reads a label column", name, str(exc), len(obs), len(obs), np.inf))

    probed = {name: fn for name, fn in features.items() if name in baseline}

    # --- probe: future outcomes hidden -----------------------------------
    for q in cutoff_quantiles:
        cutoff = obs["timestamp"].quantile(q)
        past = (obs["timestamp"] <= cutoff).to_numpy()
        hidden = _hide_outcomes_after(obs, cutoff)
        for name, fn in probed.items():
            result = _compare("future outcomes hidden", name, _label(cutoff), baseline[name][past], fn(hidden)[past])
            (report.leaks if result.changed else report.passed).append(result)

    # --- probe: own outcome hidden ---------------------------------------
    sample = _spread_sample(obs.index[obs[OUTCOME_TIME_COLUMN].notna()], obs["timestamp"], own_outcome_sample)
    changed = dict.fromkeys(probed, 0)
    max_change = dict.fromkeys(probed, 0.0)
    for idx in sample:
        masked = obs.copy()
        masked.loc[idx, OUTCOME_TIME_COLUMN] = pd.NaT
        for name, fn in probed.items():
            before = float(baseline[name].loc[idx])
            after = float(fn(masked).loc[idx])
            delta = abs(after - before)
            if delta > TOLERANCE:
                changed[name] += 1
                max_change[name] = max(max_change[name], delta)
    for name in probed:
        result = ProbeResult("own outcome hidden", name, f"{len(sample)} disputed rows", len(sample), changed[name], max_change[name])
        (report.leaks if result.changed else report.passed).append(result)

    # --- advisory probe: future rows removed -----------------------------
    already_leaking = {r.feature for r in report.leaks}
    for q in cutoff_quantiles:
        cutoff = obs["timestamp"].quantile(q)
        past = (obs["timestamp"] <= cutoff).to_numpy()
        truncated = _hide_outcomes_after(obs, cutoff)[past]
        for name, fn in probed.items():
            if name in already_leaking:
                continue
            result = _compare("future rows removed", name, _label(cutoff), baseline[name][past], fn(truncated))
            if result.changed:
                report.warnings.append(result)

    # --- advisory: a single feature that ranks fraud too well -------------
    if pipeline.LABEL in df.columns:
        split = pipeline.temporal_split(df)
        y = df.loc[split.test, pipeline.LABEL]
        if y.nunique() == 2:
            for name, values in baseline.items():
                auc = roc_auc_score(y, values.loc[split.test])
                auc = max(auc, 1.0 - auc)
                if auc > suspicious_auc:
                    report.advisories.append(
                        f"`{name}` alone ranks holdout fraud at AUC {auc:.3f} (> {suspicious_auc}). "
                        "A single feature this strong is usually reading an outcome; the model card must say why it is not."
                    )
    return report


def _hide_outcomes_after(obs: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    hidden = obs.copy()
    filed = hidden[OUTCOME_TIME_COLUMN]
    hidden[OUTCOME_TIME_COLUMN] = filed.where(filed <= cutoff)
    return hidden


def _compare(probe: str, feature: str, cutoff: str, before: pd.Series, after: pd.Series) -> ProbeResult:
    a = before.to_numpy(dtype=float)
    b = after.to_numpy(dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"{feature}: probe '{probe}' returned {b.shape} values for {a.shape} rows")
    both_nan = np.isnan(a) & np.isnan(b)
    diff = np.abs(a - b)
    diff[both_nan] = 0.0
    changed = np.nan_to_num(diff, nan=np.inf) > TOLERANCE
    return ProbeResult(probe, feature, cutoff, int(a.size), int(changed.sum()), float(diff[changed].max()) if changed.any() else 0.0)


def _spread_sample(candidates: pd.Index, timestamps: pd.Series, n: int) -> list:
    """Up to ``n`` disputed rows spread evenly across time, deterministic."""
    if len(candidates) == 0 or n <= 0:
        return []
    ordered = timestamps.loc[candidates].sort_values(kind="stable").index
    positions = np.linspace(0, len(ordered) - 1, num=min(n, len(ordered))).round().astype(int)
    return list(ordered[np.unique(positions)])


def _label(cutoff: pd.Timestamp) -> str:
    return f"T={cutoff.strftime('%Y-%m-%d')}"


def default_features(columns: Sequence[str] = pipeline.CANDIDATE_FEATURES) -> dict[str, FeatureFn]:
    fns = pipeline.feature_functions()
    return {name: fns[name] for name in columns}


def main(
    argv: Sequence[str] | None = None,
    *,
    df: pd.DataFrame | None = None,
    features: Mapping[str, FeatureFn] | None = None,
    out=None,
) -> int:
    parser = argparse.ArgumentParser(description="Gate 1 -- point-in-time correctness")
    parser.add_argument("--fail-on-leak", action="store_true", help="exit 1 if any feature leaks (report-only otherwise)")
    parser.add_argument("--own-outcome-sample", type=int, default=OWN_OUTCOME_SAMPLE)
    common.add_data_arguments(parser)
    args = parser.parse_args(argv)
    out = out or sys.stdout

    df = common.load(args) if df is None else df
    features = default_features(common.feature_columns(args)) if features is None else features
    report = run_probes(df, features, own_outcome_sample=args.own_outcome_sample)
    print(report.render(), file=out)
    if not report.ok and args.fail_on_leak:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
