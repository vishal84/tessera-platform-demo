"""Gate 3: PSI that can see a zero-inflated feature move."""

import io

import numpy as np
import pytest

from ml.validation import drift

WORKFLOW_LIMIT = 0.25  # .github/workflows/model-validation.yml


def test_identical_samples_have_zero_psi():
    x = np.random.default_rng(0).normal(size=5_000)
    assert drift.psi(x, x).value == pytest.approx(0.0, abs=1e-9)


def test_a_shifted_distribution_is_detected():
    rng = np.random.default_rng(1)
    assert drift.psi(rng.normal(0, 1, 5_000), rng.normal(1, 1, 5_000)).value > WORKFLOW_LIMIT


def test_binary_features_get_two_bins():
    rng = np.random.default_rng(2)
    result = drift.psi(rng.random(5_000) < 0.10, rng.random(5_000) < 0.30)
    assert result.n_bins == 2 and result.mass_points == (0.0, 1.0)
    assert result.value > drift.WARN_PSI


def test_a_zero_inflated_shift_is_not_hidden_by_quantile_bins():
    """
    97% zeros vs 86% zeros -- the honest card_chargeback_rate between the
    training and shadow windows. Ten quantile bins on the training sample all
    sit on zero and report PSI = 0. The mass-point binning does not.
    """
    rng = np.random.default_rng(3)
    expected = np.where(rng.random(42_000) < 0.966, 0.0, rng.uniform(0.05, 0.5, 42_000))
    actual = np.where(rng.random(18_000) < 0.858, 0.0, rng.uniform(0.05, 0.5, 18_000))

    naive_edges = np.unique(np.quantile(expected, np.linspace(0, 1, 11)))
    assert len(naive_edges) == 2, "the naive recipe collapses to one bin"

    result = drift.psi(expected, actual)
    assert 0.0 in result.mass_points
    assert result.n_bins > 2
    assert result.value > drift.WARN_PSI


def test_empty_samples_are_rejected():
    with pytest.raises(ValueError):
        drift.psi([], [1.0, 2.0])


@pytest.fixture(scope="module")
def report(transactions):
    return drift.evaluate(transactions, max_psi=WORKFLOW_LIMIT)


def test_candidate_features_are_within_the_workflow_limit(report):
    assert report.ok
    assert report.failing == []


def test_observable_features_are_stable(report):
    for name in ["amount_log", "hour_of_day", "is_night", "is_cross_border", "mcc_risk_tier", "amount_zscore_within_mcc"]:
        assert report.row(name).psi.value < 0.01, name


def test_card_chargeback_rate_is_flagged_for_review_not_failed(report):
    """
    The synthetic table starts cold on 2026-03-01: no card has any history, so
    the point-in-time rate is zero for every March row and its non-zero share
    climbs month by month as disputes get filed. That is a real shift between
    the training and recent windows, and it must show up here rather than be
    binned away -- but it is left-censoring of the data, not the population
    moving, so it belongs in the model card, not in a failing gate.
    """
    row = report.row("card_chargeback_rate")
    assert row.recent_nonzero > 3 * row.train_nonzero
    assert drift.WARN_PSI <= row.psi.value <= WORKFLOW_LIMIT
    assert row.status(report.warn_psi, report.max_psi) == "warn"
    assert "card_chargeback_rate" in report.warning


def test_the_model_score_is_checked_and_stable(report):
    assert report.row(drift.SCORE_ROW).psi.value < drift.WARN_PSI


def test_a_tight_limit_fails(transactions):
    out = io.StringIO()
    assert drift.main(["--max-psi", "0.05"], df=transactions, out=out) == 1
    assert "RESULT: FAIL -- drift above limit in card_chargeback_rate" in out.getvalue()


def test_main_passes_with_the_workflow_flag(transactions):
    out = io.StringIO()
    assert drift.main(["--max-psi", str(WORKFLOW_LIMIT)], df=transactions, out=out) == 0
    assert "RESULT: PASS with warnings" in out.getvalue()


def test_recent_days_narrows_the_window(transactions):
    narrow = drift.evaluate(transactions, recent_days=14, include_score=False)
    assert narrow.n_recent < 18_000
    assert (narrow.recent_window[1] - narrow.recent_window[0]).days <= 14
