"""Build the compact JSON snapshot used by the static GitHub Pages dashboard."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "reports" / "powerbi_dashboard_kit"
OUTPUT = ROOT / "site" / "data" / "dashboard.json"
INTEGER_COLUMNS = {
    "records", "observed_events", "review_alerts", "true_positives",
    "false_positives", "false_negatives", "alerts", "fraud_count",
    "transaction_count", "captured_fraud_count", "elapsed_dataset_hour",
    "risk_decile", "account_count", "default_count", "reviewed_account_count",
    "latest_payment_status_code",
}
FLOAT_COLUMNS = {
    "precision", "recall", "observed_event_rate", "review_rate", "pr_auc",
    "roc_auc", "decision_cutoff", "threshold", "average_fraud_score",
    "total_amount", "observed_default_rate", "average_risk_score",
}


def load_table(filename: str) -> list[dict[str, object]]:
    with (KIT / filename).open(newline="", encoding="utf-8-sig") as source:
        records: list[dict[str, object]] = []
        for row in csv.DictReader(source):
            parsed: dict[str, object] = {}
            for key, value in row.items():
                if value == "":
                    parsed[key] = None
                elif key in INTEGER_COLUMNS:
                    parsed[key] = int(value)
                elif key in FLOAT_COLUMNS:
                    parsed[key] = float(value)
                else:
                    parsed[key] = value
            records.append(parsed)
        return records


def main() -> None:
    data = {
        "metadata": {
            "project": "Card Risk Intelligence",
            "snapshot_date": "2026-10-23",
            "description": "Precomputed aggregates from an independent public-benchmark portfolio project.",
            "privacy_note": "The website contains aggregate outputs only; no account-level or customer-identifying records are included.",
        },
        "summary": load_table("risk_dashboard_summary.csv"),
        "thresholds": load_table("fraud_dashboard_thresholds.csv"),
        "hourly": load_table("fraud_dashboard_hourly.csv"),
        "deciles": load_table("credit_dashboard_deciles.csv"),
        "paymentStatus": load_table("credit_dashboard_payment_status.csv"),
        "domain": load_table("risk_dashboard_domain.csv"),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    for name in ("summary", "thresholds", "hourly", "deciles", "paymentStatus", "domain"):
        print(f"  {name}: {len(data[name])} aggregate rows")


if __name__ == "__main__":
    main()
