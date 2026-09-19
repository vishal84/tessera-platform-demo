#!/usr/bin/env python3
"""Build ml/notebooks/01_fraud_exploration.ipynb (deterministic; used by reset-demo.sh)."""

import contextlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ml" / "notebooks" / "01_fraud_exploration.ipynb"


# One namespace shared by every executed cell, so later cells see what earlier
# ones defined -- the notebook's own execution order, reproduced at build time.
NS: dict = {}


def run(src: str) -> str:
    """Execute a cell's source and return exactly what it prints.

    The outputs here used to be hand-written literals, and two had drifted from
    the data they claim to describe: the MCC table (stale counts and rates, and
    it dropped the hour breakdown entirely) and the feature-correlation table
    (card_chargeback_rate 0.601, device_card_count 0.118; really 0.285 and
    0.003). The AUC cells happened to still reproduce, which is why nobody
    noticed. The correlation cell is the one the shadow investigation cites
    when it points at the leak, so a wrong number there is worse than none.

    Running each cell's own source is the only way a stored output cannot drift
    from the code above it again. Deterministic: ml/data/generate.py has a fixed
    seed and the estimator takes random_state=0, so rebuilds stay byte-identical
    and demo/build_history.sh keeps its stable SHAs.
    """
    buf = io.StringIO()
    # Cells load ../data/transactions.parquet, relative to the notebook itself.
    with contextlib.chdir(OUT.parent), contextlib.redirect_stdout(buf):
        exec(compile(src, "<cell>", "exec"), NS)
    return buf.getvalue()


def computed(n: int, src: str) -> dict:
    """A code cell whose stored output is whatever its own source prints."""
    return code(n, src, run(src))


def corr_note() -> str:
    """The aside under the correlation cell, worded from the numbers it printed."""
    corr = NS["X"].corrwith(NS["train"].is_fraud.astype(float)).sort_values(ascending=False).round(3)
    observable = corr.drop("card_chargeback_rate")
    return (
        f"Correlation of {corr['card_chargeback_rate']:.3f} with the label from one feature — "
        f"nearly double the best observable one ({observable.idxmax()}, {observable.max():.3f}). "
        "Strongest single feature we've ever had."
    )


def md(*lines):
    return {"cell_type": "markdown", "metadata": {}, "source": "\n".join(lines)}


def code(n, src, out=None):
    cell = {
        "cell_type": "code",
        "execution_count": n,
        "metadata": {},
        "outputs": [],
        "source": src.strip("\n"),
    }
    if out:
        cell["outputs"] = [{"output_type": "stream", "name": "stdout", "text": out}]
    return cell


cells = [
    md(
        "# Fraud model v3 — exploration",
        "",
        "Scratch notebook for the Q3 fraud model refresh. **Not production code.**",
        "",
        "Current prod model (v2) does ~0.77 AUC on the holdout. Goal for v3 is 0.85+.",
        "",
        "TODO",
        "- [x] baseline with the v2 feature set",
        "- [x] try the card/merchant history features Priya built",
        "- [ ] velocity features (started, see bottom)",
        "- [ ] device graph degree",
        "- [ ] actually productionise any of this",
        "- [ ] model card for MRM review — they asked twice",
    ),
    computed(
        1,
        """
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)
""",
    ),
    computed(
        2,
        """
df = pd.read_parquet("../data/transactions.parquet").sort_values("timestamp").reset_index(drop=True)
print(df.shape)
print(f"fraud rate: {df.is_fraud.mean():.2%}")
df.head(3)
""",
    ),
    md("### where is the fraud"),
    computed(
        4,
        """
print(df.groupby("mcc").is_fraud.agg(["mean", "count"]).sort_values("mean", ascending=False))
print()
print(df.groupby(df.timestamp.dt.hour).is_fraud.mean().round(4).to_dict())
""",
    ),
    md(
        "### baseline",
        "",
        "Temporal split — 70/30 on time, **not** random. Fraud is non-stationary and a "
        "random split flatters everything.",
    ),
    computed(
        5,
        """
cut = df.timestamp.quantile(0.70)
train, test = df[df.timestamp <= cut].copy(), df[df.timestamp > cut].copy()
print(f"train={len(train):,}  test={len(test):,}")

dev_counts = df.groupby("device_id").card_token.nunique()

def base_features(d):
    return pd.DataFrame({
        "amount_log": np.log1p(d.amount_minor),
        "hour": d.timestamp.dt.hour,
        "is_night": ((d.timestamp.dt.hour >= 1) & (d.timestamp.dt.hour <= 5)).astype(int),
        "is_cross_border": d.is_cross_border,
        "mcc": d.mcc.astype("category").cat.codes,
        "device_card_count": d.device_id.map(dev_counts).fillna(1),
    }, index=d.index)

def evaluate(Xtr, Xte, label):
    m = HistGradientBoostingClassifier(max_iter=250, random_state=0).fit(Xtr, train.is_fraud)
    p = m.predict_proba(Xte)[:, 1]
    auc = roc_auc_score(test.is_fraud, p)
    ap = average_precision_score(test.is_fraud, p)
    print(f"{label:<34} AUC={auc:.4f}  PR-AUC={ap:.4f}")
    return m, auc

_, baseline_auc = evaluate(base_features(train), base_features(test), "baseline (v2 feature set)")
""",
    ),
    md(
        "### card history features",
        "",
        "Priya added these last sprint and they were a huge jump on her branch, so pulling "
        "them in here.",
        "",
        "Idea: a card that gets disputed is a card worth being suspicious about.",
    ),
    computed(
        6,
        """
# chargeback rate per card
card_cb_rate = df.groupby("card_token").chargeback_filed_at.apply(lambda s: s.notna().mean())

def with_card_history(d):
    X = base_features(d)
    X["card_chargeback_rate"] = d.card_token.map(card_cb_rate).fillna(0.0)
    return X

_, v3_auc = evaluate(with_card_history(train), with_card_history(test), "+ card_chargeback_rate")
print(f"\\nlift over baseline: {v3_auc - baseline_auc:+.4f}")
""",
    ),
    md(
        "**+0.13 AUC.** PR-AUC more than doubles (0.164 → 0.358).",
        "",
        "That blows past the 0.85 target. Priya saw the same thing on her branch so it "
        "reproduces.",
        "",
        "Need to write this up for MRM before we can ship it. Also should check it holds on "
        "the Q2 slice.",
    ),
    computed(
        9,
        """
# feature importance sanity check
X = with_card_history(train)
print(X.corrwith(train.is_fraud.astype(float)).sort_values(ascending=False).round(3))
""",
    ),
    md(corr_note()),
    md("---", "", "### scratch — velocity features, unfinished"),
    code(
        11,
        """
# transactions on the same card in the previous 24h
# TODO: this is O(n^2), need to do it with a rolling window per card
# tmp = df.sort_values(["card_token", "timestamp"])
# tmp["velocity_24h"] = tmp.groupby("card_token").timestamp.transform(
#     lambda s: s.diff().dt.total_seconds().lt(86400).cumsum()
# )
# ...abandoned, come back to this
""",
    ),
    md(
        "### notes to self",
        "",
        "- everything above is in-memory in this notebook, nothing is reusable",
        "- no tests on any of these feature definitions",
        "- the training loop is copy-pasted three times",
        "- MRM will want a model card and a fairness slice report",
        "- **how does `card_chargeback_rate` get computed at scoring time?** the batch job "
        "only refreshes nightly — need to check with platform",
    ),
]

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.11.0"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(nb, indent=1) + "\n")
print(f"wrote {OUT.relative_to(Path.cwd())} ({len(cells)} cells)")
