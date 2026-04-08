#!/usr/bin/env python3
"""
Synthetic transaction generator.

There is no real cardholder data in this repository and there never will be.
Everything downstream of this file is generated here.

The generator models one thing carefully, because the whole fraud modelling
exercise depends on it: **chargebacks arrive late**. A fraudulent transaction
on day D is typically disputed somewhere between 20 and 90 days later. That
lag is why "compute a merchant's chargeback rate" is a trap -- at scoring time
on day D you know almost nothing about day D's disputes.

Columns
-------
transaction_id, timestamp, card_token, merchant_id, mcc, device_id,
amount_minor, country, is_cross_border, is_fraud, chargeback_filed_at
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
SEED = 20260917

N_MERCHANTS = 400
N_CARDS = 6_000
N_DEVICES = 4_500
DAYS = 180


def generate(n_transactions: int = 60_000, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Merchants differ a lot in both volume and risk. Long tail of small
    # merchants is what makes a naive per-merchant aggregate so leaky.
    merchant_volume = rng.pareto(1.6, N_MERCHANTS) + 1
    merchant_weight = merchant_volume / merchant_volume.sum()
    merchant_risk = rng.beta(0.7, 40, N_MERCHANTS)  # most clean, a few hot

    mcc_pool = np.array([5411, 5812, 5999, 4789, 7995, 5967, 6011, 5732])
    mcc_risk = np.array([0.2, 0.4, 1.0, 1.3, 4.0, 3.5, 1.1, 1.6])
    merchant_mcc_idx = rng.choice(len(mcc_pool), N_MERCHANTS, p=np.ones(8) / 8)

    merchant_id = rng.choice(N_MERCHANTS, n_transactions, p=merchant_weight)
    card_idx = rng.integers(0, N_CARDS, n_transactions)
    device_idx = rng.integers(0, N_DEVICES, n_transactions)

    # A small set of devices is shared across many cards -- a real fraud signal.
    mule_devices = rng.choice(N_DEVICES, 60, replace=False)
    is_mule = np.isin(device_idx, mule_devices)
    device_idx = np.where(
        is_mule & (rng.random(n_transactions) < 0.5),
        rng.choice(mule_devices, n_transactions),
        device_idx,
    )

    seconds = rng.integers(0, DAYS * 24 * 3600, n_transactions)
    timestamp = pd.Timestamp("2026-03-01", tz="UTC") + pd.to_timedelta(seconds, unit="s")
    hour = timestamp.hour.to_numpy()

    amount_minor = np.clip(
        (rng.lognormal(mean=3.4, sigma=1.25, size=n_transactions) * 100).astype(int), 100, 5_000_00
    )
    is_cross_border = (rng.random(n_transactions) < 0.08).astype(int)

    # --- fraud propensity -------------------------------------------------
    # Genuine, learnable signal: merchant risk, MCC, odd hours, large amounts,
    # cross-border, and shared devices.
    amount_z = (np.log1p(amount_minor) - np.log1p(amount_minor).mean()) / np.log1p(
        amount_minor
    ).std()
    device_share = np.isin(device_idx, mule_devices).astype(float)

    logit = (
        -5.30
        + 4.2 * merchant_risk[merchant_id]
        + 0.85 * np.log1p(mcc_risk[merchant_mcc_idx[merchant_id]])
        + 1.35 * ((hour >= 1) & (hour <= 5)).astype(float)
        + 0.95 * amount_z
        + 1.50 * is_cross_border
        + 2.30 * device_share
    )
    p_fraud = 1 / (1 + np.exp(-logit))
    is_fraud = (rng.random(n_transactions) < p_fraud).astype(int)

    # --- chargebacks arrive late -----------------------------------------
    # ~85% of fraud is eventually disputed, 20-90 days later.
    disputed = is_fraud & (rng.random(n_transactions) < 0.85)
    lag_days = rng.integers(20, 90, n_transactions)
    chargeback_filed_at = pd.Series(pd.NaT, index=range(n_transactions), dtype="datetime64[ns, UTC]")
    chargeback_filed_at[disputed.astype(bool)] = (
        timestamp + pd.to_timedelta(lag_days, unit="D")
    )[disputed.astype(bool)]

    df = pd.DataFrame(
        {
            "transaction_id": [f"txn_{i:07d}" for i in range(n_transactions)],
            "timestamp": timestamp,
            "card_token": [f"tok_{c:06d}" for c in card_idx],
            "merchant_id": [f"mch_{m:04d}" for m in merchant_id],
            "mcc": mcc_pool[merchant_mcc_idx[merchant_id]],
            "device_id": [f"dev_{d:06d}" for d in device_idx],
            "amount_minor": amount_minor,
            "country": np.where(is_cross_border == 1, "GB", "US"),
            "is_cross_border": is_cross_border,
            "is_fraud": is_fraud,
            "chargeback_filed_at": chargeback_filed_at.to_numpy(),
        }
    ).sort_values("timestamp", ignore_index=True)

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--rows", type=int, default=60_000)
    parser.add_argument("-o", "--out", type=Path, default=OUT_DIR / "transactions.parquet")
    args = parser.parse_args()

    df = generate(args.rows)
    try:
        df.to_parquet(args.out, index=False)
        written = args.out
    except Exception:
        written = args.out.with_suffix(".csv")
        df.to_csv(written, index=False)

    print(f"wrote {len(df):,} transactions to {written.name}")
    print(f"  fraud rate        : {df.is_fraud.mean():.2%}")
    print(f"  disputed fraud    : {df.chargeback_filed_at.notna().sum():,}")
    print(f"  date range        : {df.timestamp.min().date()} .. {df.timestamp.max().date()}")
    print(f"  merchants         : {df.merchant_id.nunique():,}")
    print(f"  median dispute lag: {(df.chargeback_filed_at - df.timestamp).median().days} days")


if __name__ == "__main__":
    main()
