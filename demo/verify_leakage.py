"""
Reproduce the leakage numbers, live.

    uv run python demo/verify_leakage.py

Three models on a temporal split: observable features only, plus the
per-card chargeback rate computed over the whole dataset (leaky), plus the
same feature computed point-in-time. The honest lift is the finding.

The functions are importable -- demo/generate_shadow_report.py reuses them so
the registry, the notebook and this script can never disagree.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "ml" / "data" / "transactions.parquet"
BASE_COLUMNS = ["amount_log", "hour", "is_night", "is_cross_border", "mcc", "device_card_count"]


def load(path: pathlib.Path = DATA) -> pd.DataFrame:
    return pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)


def split(df: pd.DataFrame, quantile: float = 0.70) -> tuple[pd.DataFrame, pd.DataFrame]:
    cut = df.timestamp.quantile(quantile)
    return df[df.timestamp <= cut].copy(), df[df.timestamp > cut].copy()


def base_features(df_all: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    """Observable-at-scoring-time features, as in notebook 01."""
    dev_counts = df_all.groupby("device_id").card_token.nunique()
    return pd.DataFrame({
        "amount_log": np.log1p(d.amount_minor),
        "hour": d.timestamp.dt.hour,
        "is_night": ((d.timestamp.dt.hour >= 1) & (d.timestamp.dt.hour <= 5)).astype(int),
        "is_cross_border": d.is_cross_border,
        "mcc": d.mcc.astype("category").cat.codes,
        "device_card_count": d.device_id.map(dev_counts).fillna(1),
    }, index=d.index)


def leaky_rate(df_all: pd.DataFrame) -> pd.Series:
    """Per-card chargeback rate over the FULL dataset -- includes each row's own future."""
    return df_all.groupby("card_token").chargeback_filed_at.apply(lambda s: s.notna().mean())


def pit_rate(df_all: pd.DataFrame, d: pd.DataFrame) -> np.ndarray:
    """The same feature, using only chargebacks filed before each transaction."""
    txn_t, cb_t = {}, {}
    for card, g in df_all.groupby("card_token"):
        txn_t[card] = np.sort(g.timestamp.to_numpy())
        cb_t[card] = np.sort(g.chargeback_filed_at.dropna().to_numpy())
    out = np.zeros(len(d))
    for i, (card, t) in enumerate(zip(d.card_token.to_numpy(), d.timestamp.to_numpy())):
        n = np.searchsorted(txn_t[card], t, side="left")
        out[i] = 0.0 if n == 0 else np.searchsorted(cb_t[card], t, side="left") / n
    return out


def fit(X: pd.DataFrame, y: pd.Series) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(max_iter=250, random_state=0).fit(X, y)


def score(model: HistGradientBoostingClassifier, X: pd.DataFrame, y: pd.Series) -> tuple[float, float]:
    p = model.predict_proba(X)[:, 1]
    return float(roc_auc_score(y, p)), float(average_precision_score(y, p))


def main() -> None:
    df = load()
    train, test = split(df)
    Xtr, Xte = base_features(df, train), base_features(df, test)
    print(f"train={len(train):,}  test={len(test):,}  test fraud rate={test.is_fraud.mean():.2%}\n")

    def run(name: str, tr, te) -> float:
        xtr, xte = Xtr.copy(), Xte.copy()
        if tr is not None:
            xtr["card_chargeback_rate"] = np.asarray(tr)
            xte["card_chargeback_rate"] = np.asarray(te)
        auc, ap = score(fit(xtr, train.is_fraud), xte, test.is_fraud)
        print(f"  {name:<50} AUC={auc:.4f}  PR-AUC={ap:.4f}")
        return auc

    rate = leaky_rate(df)
    a = run("baseline (observable features only)", None, None)
    b = run("+ card_chargeback_rate   [LEAKY, full data]", train.card_token.map(rate), test.card_token.map(rate))
    c = run("+ card_chargeback_rate_pit   [point-in-time]", pit_rate(df, train), pit_rate(df, test))
    print(f"\n  leaky lift   : {b - a:+.4f}")
    print(f"  honest lift  : {c - a:+.4f}")
    print(f"  phantom lift : {b - c:+.4f}")


if __name__ == "__main__":
    main()
