"""Download and normalize UCI's public credit default benchmark."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from ucimlrepo import fetch_ucirepo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_PATH = DATA_DIR / "uci_credit_default.csv"
METADATA_PATH = DATA_DIR / "uci_credit_default_source.json"

FEATURE_NAMES = [
    "LIMIT_BAL",
    "SEX",
    "EDUCATION",
    "MARRIAGE",
    "AGE",
    "PAY_0",
    "PAY_2",
    "PAY_3",
    "PAY_4",
    "PAY_5",
    "PAY_6",
    "BILL_AMT1",
    "BILL_AMT2",
    "BILL_AMT3",
    "BILL_AMT4",
    "BILL_AMT5",
    "BILL_AMT6",
    "PAY_AMT1",
    "PAY_AMT2",
    "PAY_AMT3",
    "PAY_AMT4",
    "PAY_AMT5",
    "PAY_AMT6",
]
TARGET_NAME = "default_payment_next_month"


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading UCI dataset 350: Default of Credit Card Clients...")
    dataset = fetch_ucirepo(id=350)
    features = dataset.data.features
    target = dataset.data.targets

    if features.shape[1] != len(FEATURE_NAMES):
        raise ValueError(
            f"Expected {len(FEATURE_NAMES)} predictor columns, found {features.shape[1]}. "
            "Review the UCI schema before using this data."
        )
    if target.shape[1] != 1:
        raise ValueError(f"Expected one target column, found {target.shape[1]}.")

    normalized = pd.DataFrame(features.to_numpy(), columns=FEATURE_NAMES)
    normalized[TARGET_NAME] = target.iloc[:, 0].to_numpy()
    for name in normalized.columns:
        normalized[name] = pd.to_numeric(normalized[name], errors="coerce")
    if normalized.isna().any().any():
        null_counts = normalized.isna().sum()
        raise ValueError(
            "UCI data contains missing or non-numeric values after normalization: "
            f"{null_counts[null_counts > 0].to_dict()}"
        )
    observed_labels = set(normalized[TARGET_NAME].astype(int).unique())
    if observed_labels != {0, 1}:
        raise ValueError(f"Expected binary target values 0 and 1; found {observed_labels}.")

    normalized[TARGET_NAME] = normalized[TARGET_NAME].astype("int64")
    normalized.to_csv(OUTPUT_PATH, index=False)
    metadata = {
        "dataset": "Default of Credit Card Clients",
        "repository": "UCI Machine Learning Repository",
        "uci_id": 350,
        "doi": "10.24432/C55S3H",
        "license": "CC BY 4.0",
        "source_url": "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(normalized)),
        "columns": list(normalized.columns),
        "target": TARGET_NAME,
        "output_file": OUTPUT_PATH.name,
        "note": "Historical Taiwan bank dataset; not American Express or U.S. underwriting data.",
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Rows: {len(normalized):,}")
    print(f"Default rate: {normalized[TARGET_NAME].mean():.3%}")
    print(f"CSV saved to: {OUTPUT_PATH}")
    print(f"Source metadata saved to: {METADATA_PATH}")


if __name__ == "__main__":
    main()
