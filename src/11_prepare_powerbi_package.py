"""Build a Power BI import kit from the project's completed local model outputs."""

from __future__ import annotations

import csv
import json
import zipfile
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "processed"
REPORT_DIR = PROJECT_ROOT / "reports"
PACKAGE_DIR = REPORT_DIR / "powerbi_import"
ZIP_PATH = REPORT_DIR / "powerbi_dashboard_kit.zip"


def read_json(filename: str) -> dict:
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Required model output is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(filename: str) -> list[dict[str, str]]:
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Required model output is missing: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as source:
        return list(csv.DictReader(source))


def write_csv(filename: str, columns: list[str], rows: list[dict]) -> Path:
    path = PACKAGE_DIR / filename
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def build_summary(fraud_metrics: dict, credit_metrics: dict) -> list[dict]:
    fraud_records = int(fraud_metrics["holdout_rows"])
    fraud_events = int(fraud_metrics["holdout_fraud_rows"])
    credit_records = int(credit_metrics["test_accounts"])
    credit_events = int(credit_metrics["test_defaults"])
    return [
        {
            "risk_domain": "Fraud",
            "sample_name": "Later-time holdout",
            "records": fraud_records,
            "observed_events": fraud_events,
            "review_alerts": int(fraud_metrics["alerts"]),
            "true_positives": int(fraud_metrics["true_positives"]),
            "false_positives": int(fraud_metrics["false_positives"]),
            "false_negatives": int(fraud_metrics["false_negatives"]),
            "precision": float(fraud_metrics["precision"]),
            "recall": float(fraud_metrics["recall"]),
            "observed_event_rate": ratio(fraud_events, fraud_records),
            "review_rate": ratio(fraud_metrics["alerts"], fraud_records),
            "pr_auc": float(fraud_metrics["holdout_pr_auc"]),
            "roc_auc": float(fraud_metrics["holdout_roc_auc"]),
            "decision_cutoff": float(fraud_metrics["selected_threshold"]),
            "decision_policy": fraud_metrics["threshold_selection_note"],
        },
        {
            "risk_domain": "Credit Default",
            "sample_name": "Seeded random test split",
            "records": credit_records,
            "observed_events": credit_events,
            "review_alerts": int(credit_metrics["test_review_accounts"]),
            "true_positives": int(credit_metrics["test_defaults_captured"]),
            "false_positives": int(credit_metrics["test_false_alerts"]),
            "false_negatives": int(credit_metrics["test_missed_defaults"]),
            "precision": float(credit_metrics["test_precision"]),
            "recall": float(credit_metrics["test_default_capture_rate"]),
            "observed_event_rate": float(credit_metrics["test_default_rate"]),
            "review_rate": float(credit_metrics["test_review_rate"]),
            "pr_auc": float(credit_metrics["test_pr_auc"]),
            "roc_auc": float(credit_metrics["test_roc_auc"]),
            "decision_cutoff": float(credit_metrics["selected_review_threshold"]),
            "decision_policy": credit_metrics["threshold_policy"],
        },
    ]


def build_fraud_hourly(scores: list[dict[str, str]]) -> list[dict]:
    grouped: dict[int, dict[str, float | int]] = defaultdict(
        lambda: {
            "transaction_count": 0,
            "fraud_count": 0,
            "alert_count": 0,
            "captured_fraud_count": 0,
            "fraud_score_sum": 0.0,
            "total_amount": 0.0,
        }
    )
    for row in scores:
        hour = int(float(row["elapsed_seconds"]) // 3600)
        actual = int(row["actual_fraud"])
        flagged = int(row["model_flag"])
        bucket = grouped[hour]
        bucket["transaction_count"] += 1
        bucket["fraud_count"] += actual
        bucket["alert_count"] += flagged
        bucket["captured_fraud_count"] += int(actual == 1 and flagged == 1)
        bucket["fraud_score_sum"] += float(row["fraud_score"])
        bucket["total_amount"] += float(row["Amount"])

    return [
        {
            "risk_domain": "Fraud",
            "elapsed_dataset_hour": hour,
            "transaction_count": values["transaction_count"],
            "fraud_count": values["fraud_count"],
            "alert_count": values["alert_count"],
            "captured_fraud_count": values["captured_fraud_count"],
            "average_fraud_score": ratio(values["fraud_score_sum"], values["transaction_count"]),
            "total_amount": round(values["total_amount"], 2),
        }
        for hour, values in sorted(grouped.items())
    ]


def build_credit_groups(scores: list[dict[str, str]], group_field: str) -> list[dict]:
    grouped: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "account_count": 0,
            "default_count": 0,
            "reviewed_account_count": 0,
            "risk_score_sum": 0.0,
        }
    )
    for row in scores:
        key = row[group_field]
        bucket = grouped[key]
        bucket["account_count"] += 1
        bucket["default_count"] += int(row["actual_default"])
        bucket["reviewed_account_count"] += int(row["review_flag"])
        bucket["risk_score_sum"] += float(row["risk_score"])

    return [
        {
            "account_count": values["account_count"],
            "default_count": values["default_count"],
            "observed_default_rate": ratio(values["default_count"], values["account_count"]),
            "average_risk_score": ratio(values["risk_score_sum"], values["account_count"]),
            "reviewed_account_count": values["reviewed_account_count"],
            "risk_domain": "Credit Default",
            group_field: int(key),
        }
        for key, values in sorted(grouped.items(), key=lambda item: int(item[0]))
    ]


def main() -> None:
    fraud_metrics = read_json("fraud_model_metrics.json")
    credit_metrics = read_json("credit_default_metrics.json")
    fraud_scores = read_csv("fraud_holdout_scores.csv")
    threshold_rows = read_csv("fraud_validation_thresholds.csv")
    credit_scores = read_csv("credit_default_test_scores.csv")

    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)

    domain_rows = [
        {
            "risk_domain": "Fraud",
            "dataset_context": "Public ULB/Kaggle benchmark; anonymized features; time-based holdout; not Amex data.",
        },
        {
            "risk_domain": "Credit Default",
            "dataset_context": "Historical UCI Taiwan bank benchmark; seeded random split; not U.S. lending data.",
        },
    ]
    write_csv("risk_dashboard_domain.csv", ["risk_domain", "dataset_context"], domain_rows)

    summary_columns = [
        "risk_domain", "sample_name", "records", "observed_events", "review_alerts",
        "true_positives", "false_positives", "false_negatives", "precision", "recall",
        "observed_event_rate", "review_rate", "pr_auc", "roc_auc", "decision_cutoff",
        "decision_policy",
    ]
    write_csv("risk_dashboard_summary.csv", summary_columns, build_summary(fraud_metrics, credit_metrics))

    threshold_columns = [
        "risk_domain", "threshold", "alerts", "true_positives", "false_positives",
        "false_negatives", "precision", "recall",
    ]
    for row in threshold_rows:
        row["risk_domain"] = "Fraud"
    write_csv("fraud_dashboard_thresholds.csv", threshold_columns, threshold_rows)

    hourly_rows = build_fraud_hourly(fraud_scores)
    write_csv(
        "fraud_dashboard_hourly.csv",
        ["risk_domain", "elapsed_dataset_hour", "transaction_count", "fraud_count", "alert_count",
         "captured_fraud_count", "average_fraud_score", "total_amount"],
        hourly_rows,
    )

    decile_rows = build_credit_groups(credit_scores, "risk_decile")
    write_csv(
        "credit_dashboard_deciles.csv",
        ["risk_domain", "risk_decile", "account_count", "default_count", "observed_default_rate",
         "average_risk_score", "reviewed_account_count"],
        decile_rows,
    )

    status_rows = build_credit_groups(credit_scores, "latest_payment_status")
    for row in status_rows:
        row["latest_payment_status_code"] = row.pop("latest_payment_status")
    write_csv(
        "credit_dashboard_payment_status.csv",
        ["risk_domain", "latest_payment_status_code", "account_count", "default_count",
         "observed_default_rate", "average_risk_score", "reviewed_account_count"],
        status_rows,
    )

    package_readme = """CARD RISK ANALYTICS — POWER BI IMPORT KIT

This folder contains six model-ready CSV tables generated from the completed
local benchmark outputs, a Power BI theme, the Azure Databricks notebook and
setup guide, and a static HTML dashboard preview.

LOCAL POWER BI IMPORT
1. In Power BI Desktop, choose Home > Get data > Text/CSV.
2. Import the six CSV files in this folder.
3. In Model view, create one-to-many, single-direction relationships from
   risk_dashboard_domain[risk_domain] to risk_domain in each other table.
4. Apply powerbi_theme.json through View > Themes > Browse for themes.
5. Follow POWER_BI_AZURE_GUIDE.md for DAX measures and page layouts.

CLOUD-CONNECTED VERSION
The CSVs are local snapshots. For cloud integration, run the included
Azure Databricks notebook and connect Power BI to its Unity Catalog Delta
serving tables through a Databricks SQL warehouse, as described in the guide.

This package does not contain a signed-in .pbix file. Power BI Desktop and
your Microsoft/Azure account are needed to create and publish that report.
The public Kaggle/UCI benchmarks are not Amex data and do not represent
Amex production performance.
"""
    (PACKAGE_DIR / "README.txt").write_text(package_readme, encoding="utf-8")

    assets = [
        PACKAGE_DIR / name
        for name in [
            "README.txt",
            "risk_dashboard_domain.csv",
            "risk_dashboard_summary.csv",
            "fraud_dashboard_thresholds.csv",
            "fraud_dashboard_hourly.csv",
            "credit_dashboard_deciles.csv",
            "credit_dashboard_payment_status.csv",
        ]
    ]
    assets.extend([
        REPORT_DIR / "powerbi_theme.json",
        REPORT_DIR / "POWER_BI_AZURE_GUIDE.md",
        PROJECT_ROOT / "notebooks" / "azure_databricks_pipeline.py",
        REPORT_DIR / "risk_analytics_dashboard.html",
    ])

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in assets:
            archive.write(path, arcname=path.name)

    print(f"Created Power BI CSV import tables in: {PACKAGE_DIR}")
    print(f"Created Power BI handoff package: {ZIP_PATH}")
    print("The ZIP contains import-ready CSVs, theme, Azure guide, Databricks notebook, and HTML preview.")
    print("A signed-in Power BI Desktop session is still needed to save/publish a .pbix report.")


if __name__ == "__main__":
    main()
