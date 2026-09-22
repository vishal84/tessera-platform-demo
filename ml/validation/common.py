"""Shared plumbing for the validation gates: arguments, loading, formatting."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from ml.fraud import pipeline

FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "candidate": pipeline.CANDIDATE_FEATURES,
    "champion": pipeline.CHAMPION_FEATURES,
}


def add_data_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data",
        type=Path,
        default=pipeline.DATA_PATH,
        help="transactions parquet (default: the synthetic set under ml/data/)",
    )
    parser.add_argument(
        "--split",
        type=float,
        default=pipeline.SPLIT_FRACTION,
        help="temporal split fraction; rows up to this quantile of time train",
    )
    parser.add_argument(
        "--features",
        choices=sorted(FEATURE_SETS),
        default="candidate",
        help="which registered feature set to validate",
    )


def load(args: argparse.Namespace) -> pd.DataFrame:
    return pipeline.load_transactions(args.data)


def feature_columns(args: argparse.Namespace) -> tuple[str, ...]:
    return FEATURE_SETS[args.features]


def month_of(timestamps: pd.Series) -> pd.Series:
    """Calendar month label without the timezone warning ``to_period`` emits."""
    return timestamps.dt.strftime("%Y-%m")


def fmt(value: object, digits: int = 4) -> str:
    if isinstance(value, float | np.floating):
        if np.isnan(value):
            return "n/a"
        return f"{value:.{digits}f}"
    if isinstance(value, int | np.integer):
        return f"{int(value):,}"
    return str(value)


def markdown_table(rows: Iterable[Mapping[str, object]], columns: Sequence[str], digits: int = 4) -> str:
    """A GitHub-flavoured markdown table. Numbers right-aligned by the reader's eye, not ours."""
    rows = list(rows)
    header = "| " + " | ".join(columns) + " |"
    rule = "|" + "|".join("---" for _ in columns) + "|"
    body = ["| " + " | ".join(fmt(row.get(c, ""), digits) for c in columns) + " |" for row in rows]
    return "\n".join([header, rule, *body])
