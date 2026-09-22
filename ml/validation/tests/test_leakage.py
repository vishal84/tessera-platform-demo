"""
Gate 1 must fail on the definition that reached shadow and pass on the
point-in-time one. Everything else in ml/validation/ rests on this.
"""

import io

import pandas as pd
import pytest

from ml.fraud import pipeline
from ml.validation import leakage
from ml.validation.tests.leaky_fixtures import (
    leaky_feature_functions,
    notebook01_card_chargeback_rate,
    notebook01_device_card_count,
)

SAMPLE = 5  # disputed rows for the own-outcome probe; enough to fail, fast enough to run every push


@pytest.fixture(scope="module")
def leaky_report(transactions):
    return leakage.run_probes(transactions, leaky_feature_functions(), own_outcome_sample=SAMPLE)


@pytest.fixture(scope="module")
def clean_report(transactions):
    return leakage.run_probes(transactions, leakage.default_features(), own_outcome_sample=SAMPLE)


def test_gate_1_fails_on_the_notebook_definition(leaky_report):
    assert not leaky_report.ok
    assert leaky_report.leaking_features == ["card_chargeback_rate"]


def test_every_blocking_probe_catches_it(leaky_report):
    probes = {r.probe for r in leaky_report.leaks}
    assert probes == {"future outcomes hidden", "own outcome hidden"}
    own = [r for r in leaky_report.leaks if r.probe == "own outcome hidden"][0]
    assert own.rows_changed == own.rows_compared, "hiding a row's own dispute must move its own feature every time"


def test_only_the_leaky_feature_is_blamed(leaky_report):
    """The base features share the frame; the gate must not smear them."""
    passed = {r.feature for r in leaky_report.passed}
    assert passed == set(pipeline.CANDIDATE_FEATURES) - {"card_chargeback_rate"}


def test_the_leaky_feature_trips_the_single_feature_advisory(leaky_report):
    assert any("`card_chargeback_rate` alone ranks holdout fraud" in line for line in leaky_report.advisories)


def test_gate_1_passes_on_the_point_in_time_definition(clean_report):
    assert clean_report.ok
    assert clean_report.leaking_features == []
    assert {r.feature for r in clean_report.passed} == set(pipeline.CANDIDATE_FEATURES)


def test_the_point_in_time_feature_does_not_trip_the_advisory(clean_report):
    assert not any("card_chargeback_rate" in line for line in clean_report.advisories)


def test_frame_wide_statistics_are_advisory_not_blocking(clean_report):
    """amount_zscore_within_mcc uses the whole frame's mean; that is a fit-before-split, not a leak."""
    assert {r.feature for r in clean_report.warnings} == {"amount_zscore_within_mcc"}


def test_a_full_table_device_count_is_advisory_not_blocking(transactions):
    fns = leakage.default_features()
    fns["device_card_count"] = notebook01_device_card_count
    report = leakage.run_probes(transactions, fns, own_outcome_sample=2)
    assert report.ok
    assert "device_card_count" in {r.feature for r in report.warnings}


def test_a_feature_that_reads_the_label_is_a_leak(transactions):
    fns = {"reads_label": lambda frame: frame["is_fraud"].astype(float)}
    report = leakage.run_probes(transactions, fns, own_outcome_sample=2)
    assert report.leaking_features == ["reads_label"]
    assert report.leaks[0].probe == "reads a label column"


def test_the_two_definitions_disagree_on_the_training_table(transactions):
    """Same name, two features. This is the number the shadow report calls training_nonzero_share."""
    obs = pipeline.observable_frame(transactions)
    leaky = notebook01_card_chargeback_rate(obs)
    honest = pipeline.feature_functions()["card_chargeback_rate"](obs)
    split = pipeline.temporal_split(transactions)
    assert (leaky.loc[split.train] > 0).mean() == pytest.approx(0.2743, abs=5e-4)
    assert (honest.loc[split.test] > 0).mean() == pytest.approx(0.1419, abs=5e-4)


def test_main_exits_1_with_fail_on_leak_and_0_without(transactions):
    out = io.StringIO()
    leaky = leaky_feature_functions()
    assert leakage.main(["--fail-on-leak", "--own-outcome-sample", str(SAMPLE)], df=transactions, features=leaky, out=out) == 1
    assert "RESULT: LEAK in card_chargeback_rate" in out.getvalue()
    assert leakage.main(["--own-outcome-sample", str(SAMPLE)], df=transactions, features=leaky, out=io.StringIO()) == 0


def test_main_exits_0_on_the_pipeline_features(transactions):
    out = io.StringIO()
    assert leakage.main(["--fail-on-leak", "--own-outcome-sample", str(SAMPLE)], df=transactions, out=out) == 0
    assert "RESULT: no leak detected" in out.getvalue()


def test_the_report_names_every_probe_and_feature(clean_report):
    text = clean_report.render()
    for feature in pipeline.CANDIDATE_FEATURES:
        assert feature in text
    assert "future outcomes hidden" in text and "own outcome hidden" in text


def test_probes_are_deterministic(transactions):
    a = leakage.run_probes(transactions, leaky_feature_functions(), own_outcome_sample=3)
    b = leakage.run_probes(transactions, leaky_feature_functions(), own_outcome_sample=3)
    assert [r.as_row() for r in a.leaks] == [r.as_row() for r in b.leaks]


def test_hidden_outcomes_never_touch_rows_before_the_cutoff():
    """The probe's own helper: hiding after T must leave everything at or before T alone."""
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"], utc=True),
            "chargeback_filed_at": pd.to_datetime(["2026-01-20", "2026-03-15", None], utc=True),
        }
    )
    hidden = leakage._hide_outcomes_after(frame, pd.Timestamp("2026-02-01", tz="UTC"))
    assert hidden["chargeback_filed_at"].notna().tolist() == [True, False, False]
