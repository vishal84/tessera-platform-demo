"""Gate 2: the floor is measured on a temporal split, at the operating point, and never trusted alone."""

import io

import numpy as np
import pytest

from ml.fraud import pipeline
from ml.validation import performance
from ml.validation.tests.leaky_fixtures import leaky_feature_frame

WORKFLOW_FLOOR = 0.15  # .github/workflows/model-validation.yml


@pytest.fixture(scope="module")
def report(transactions):
    return performance.evaluate(transactions, min_pr_auc=WORKFLOW_FLOOR)


def test_candidate_clears_the_recorded_floor(report):
    assert report.ok
    assert report.overall.pr_auc >= WORKFLOW_FLOOR


def test_the_honest_number_is_the_champion_not_the_notebook(report):
    """0.906 was the leak. Point-in-time, the candidate is the champion within noise."""
    assert report.overall.auc == pytest.approx(0.778, abs=0.01)
    assert report.overall.pr_auc < 0.20
    assert report.champion is not None
    assert abs(report.overall.auc - report.champion.auc) < 0.01


def test_not_beating_the_champion_is_an_advisory_not_a_pass(report):
    assert any("does not beat the champion" in line for line in report.advisories)


def test_by_month_rows_partition_the_holdout(report):
    assert [m.label for m in report.by_month] == ["2026-07", "2026-08"]
    assert sum(m.n for m in report.by_month) == report.overall.n
    assert sum(m.positives for m in report.by_month) == report.overall.positives


def test_operating_point_is_set_on_training_scores(transactions, report):
    trained = pipeline.train(transactions)
    assert report.threshold == pytest.approx(pipeline.review_threshold(trained.train_scores))
    assert report.overall.flag_rate == pytest.approx(pipeline.REVIEW_BUDGET, abs=0.02)


def test_the_leaky_definition_clears_any_floor_which_is_why_gate_1_runs_first(transactions):
    leaky = performance.evaluate(transactions, X=leaky_feature_frame(transactions), min_pr_auc=WORKFLOW_FLOOR)
    honest = performance.evaluate(transactions, min_pr_auc=WORKFLOW_FLOOR)
    assert leaky.ok and honest.ok
    assert leaky.overall.pr_auc > 0.30 > honest.overall.pr_auc
    assert leaky.overall.auc > 0.88 > honest.overall.auc


def test_an_unreachable_floor_fails(transactions):
    out = io.StringIO()
    assert performance.main(["--min-pr-auc", "0.99"], df=transactions, out=out) == 1
    assert "RESULT: FAIL" in out.getvalue()


def test_main_passes_with_the_workflow_flags(transactions):
    out = io.StringIO()
    assert performance.main(["--min-pr-auc", str(WORKFLOW_FLOOR)], df=transactions, out=out) == 0
    text = out.getvalue()
    assert "RESULT: PASS" in text and "champion (same split)" in text and "2026-08" in text


def test_the_champion_feature_set_can_be_validated_too(transactions):
    out = io.StringIO()
    assert performance.main(["--min-pr-auc", str(WORKFLOW_FLOOR), "--features", "champion"], df=transactions, out=out) == 0
    assert "champion (same split)" not in out.getvalue()


def test_metrics_are_nan_not_zero_when_undefined():
    m = performance.metrics("no fraud", np.zeros(10, dtype=int), np.linspace(0, 1, 10), threshold=0.5)
    assert np.isnan(m.auc) and np.isnan(m.pr_auc) and np.isnan(m.recall) and np.isnan(m.pr_auc)
    assert m.fpr == pytest.approx(0.5)
    with pytest.raises(ValueError):
        performance.metrics("shape", np.zeros(3, dtype=int), np.zeros(4), threshold=0.5)
