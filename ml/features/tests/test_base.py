import numpy as np
import pandas as pd
import pytest

from ml.features.base import BASE_FEATURES, build


@pytest.fixture
def frame():
    return pd.DataFrame(
        {
            "transaction_id": ["txn_1", "txn_2", "txn_3"],
            "timestamp": pd.to_datetime(
                ["2026-05-01T03:15:00Z", "2026-05-01T14:00:00Z", "2026-05-02T02:00:00Z"]
            ),
            "amount_minor": [1_000, 250_000, 4_500],
            "mcc": [5411, 7995, 5411],
            "is_cross_border": [0, 1, 0],
        }
    )


def test_build_returns_every_declared_feature(frame):
    out = build(frame)
    assert set(out.columns) == set(BASE_FEATURES)
    assert len(out) == len(frame)


def test_night_flag_matches_the_01_to_05_window(frame):
    assert build(frame)["is_night"].tolist() == [1, 0, 1]


def test_mcc_risk_tier_falls_back_for_unknown_codes(frame):
    frame.loc[0, "mcc"] = 9999
    assert build(frame)["mcc_risk_tier"].iloc[0] == 3


def test_no_feature_reads_a_label_or_outcome_column(frame):
    """
    Guard against the obvious version of the mistake: a base feature reaching
    for is_fraud or chargeback_filed_at. These columns are not passed in, so
    touching one raises rather than silently leaking.
    """
    for name, fn in BASE_FEATURES.items():
        result = fn(frame)
        assert len(result) == len(frame), name


def test_features_are_finite(frame):
    out = build(frame)
    assert np.isfinite(out.to_numpy(dtype=float)).all()
