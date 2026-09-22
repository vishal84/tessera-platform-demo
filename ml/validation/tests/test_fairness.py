"""Gate 4: every slice reported, disparities named, blocking only when asked."""

import io

import numpy as np
import pytest

from ml.validation import fairness


@pytest.fixture(scope="module")
def report(transactions):
    return fairness.evaluate(transactions)


def test_every_dimension_is_reported(report):
    assert report.dimensions == list(fairness.SLICES)


def test_slices_partition_the_holdout(report):
    for dim in report.dimensions:
        rows = report.dimension(dim)
        assert sum(s.metrics.n for s in rows) == report.overall.n, dim
        assert sum(s.metrics.positives for s in rows) == report.overall.positives, dim
        assert sum(s.reference for s in rows) == 1, dim


def test_cross_border_disparity_is_surfaced(report):
    """Cross-border rows carry ~3x the fraud rate and the model flags them ~8x as often. Say so."""
    cross = next(s for s in report.dimension("is_cross_border") if s.name == "cross-border")
    assert not cross.reference
    assert cross.fpr_ratio > 1.25
    assert cross.disparate
    assert "review" in cross.note()
    assert cross in report.flagged_for_review


def test_country_is_the_same_slice_as_cross_border(report):
    gb = next(s for s in report.dimension("country") if s.name == "GB")
    cross = next(s for s in report.dimension("is_cross_border") if s.name == "cross-border")
    assert gb.metrics.n == cross.metrics.n
    assert gb.metrics.fpr == pytest.approx(cross.metrics.fpr)


def test_small_slices_are_marked(report):
    tiny = [s for s in report.slices if s.metrics.n < fairness.MIN_SLICE_ROWS]
    for s in tiny:
        assert "small slice" in s.note()


def test_report_is_written_and_exits_0_by_default(transactions, tmp_path):
    path = tmp_path / "fairness.md"
    out = io.StringIO()
    assert fairness.main(["--report", str(path)], df=transactions, out=out) == 0
    text = path.read_text()
    for dim in fairness.SLICES:
        assert f"## {dim}" in text
    assert "## Flagged for review" in text
    assert "RESULT: PASS" in text


def test_disparity_threshold_makes_the_gate_blocking(transactions, tmp_path):
    path = tmp_path / "fairness.md"
    out = io.StringIO()
    assert fairness.main(["--report", str(path), "--fail-on-disparity", "1.25"], df=transactions, out=out) == 1
    assert "RESULT: FAIL" in path.read_text()


def test_ratio_is_nan_when_the_reference_has_no_false_positives():
    assert np.isnan(fairness._ratio(0.1, 0.0))
    assert np.isnan(fairness._ratio(float("nan"), 0.1))
    assert fairness._ratio(0.2, 0.1) == pytest.approx(2.0)
