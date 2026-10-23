"""Build a self-contained HTML portfolio dashboard from generated model outputs."""

from __future__ import annotations

import base64
import csv
import html
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "processed"
REPORT_DIR = PROJECT_ROOT / "reports"


def read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required model metrics are missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def chart_as_base64(fig: plt.Figure) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight", facecolor="#ffffff")
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def format_rate(value: float) -> str:
    return f"{value:.1%}"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as source_file:
        return list(csv.DictReader(source_file))


fraud_metrics = read_json(DATA_DIR / "fraud_model_metrics.json")
fraud_scores_path = DATA_DIR / "fraud_holdout_scores.csv"
credit_metrics_path = DATA_DIR / "credit_default_metrics.json"
credit_deciles_path = DATA_DIR / "credit_default_deciles.csv"
if not fraud_scores_path.exists():
    raise FileNotFoundError(
        f"Fraud holdout scores are missing: {fraud_scores_path}. Run src/07_select_threshold.py first."
    )
credit_ready = credit_metrics_path.exists() and credit_deciles_path.exists()
credit_metrics = read_json(credit_metrics_path) if credit_ready else None

fraud_scores = read_csv_rows(fraud_scores_path)
credit_deciles = (
    sorted(read_csv_rows(credit_deciles_path), key=lambda row: int(row["risk_decile"]))
    if credit_ready
    else []
)

fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.2))
for label, color, name in [(0, "#5b83c4", "Legitimate"), (1, "#dc5b62", "Fraud")]:
    scores = [
        float(row["fraud_score"])
        for row in fraud_scores
        if int(row["actual_fraud"]) == label
    ]
    if scores:
        axes[0].hist(scores, bins=40, density=True, alpha=0.62, color=color, label=name)
axes[0].set_title("Fraud score distribution on untouched holdout")
axes[0].set_xlabel("Model score (not a calibrated probability)")
axes[0].set_ylabel("Density")
axes[0].legend(frameon=False)
axes[0].spines[["top", "right"]].set_visible(False)

if credit_ready:
    axes[1].bar(
        [str(int(row["risk_decile"])) for row in credit_deciles],
        [float(row["observed_default_rate"]) * 100 for row in credit_deciles],
        color=["#c6525d" if i < 3 else "#6787bd" for i in range(len(credit_deciles))],
    )
    axes[1].set_title("Observed default by test-set risk decile")
    axes[1].set_xlabel("Risk decile (1 = highest score)")
    axes[1].set_ylabel("Observed default rate (%)")
    axes[1].spines[["top", "right"]].set_visible(False)
    axes[1].grid(axis="y", color="#e8edf3", linewidth=0.8)
    axes[1].set_axisbelow(True)
else:
    axes[1].axis("off")
    axes[1].text(
        0.5, 0.58, "Credit-default track is ready to run",
        ha="center", va="center", fontsize=15, color="#17243b", weight="bold",
    )
    axes[1].text(
        0.5, 0.43, "Download the UCI benchmark, then run scripts 08 and 09.",
        ha="center", va="center", fontsize=11, color="#64748b",
    )
chart = chart_as_base64(fig)

fraud_cards = [
    ("Holdout PR AUC", f"{fraud_metrics['holdout_pr_auc']:.3f}"),
    ("Fraud recall", format_rate(fraud_metrics["recall"])),
    ("Alert precision", format_rate(fraud_metrics["precision"])),
    ("Alerts for review", f"{fraud_metrics['alerts']:,}"),
]
credit_cards = (
    [
        ("Test PR AUC", f"{credit_metrics['test_pr_auc']:.3f}"),
        ("Test ROC AUC", f"{credit_metrics['test_roc_auc']:.3f}"),
        ("Review queue", format_rate(credit_metrics["test_review_rate"])),
        ("Defaults captured", format_rate(credit_metrics["test_default_capture_rate"])),
    ]
    if credit_ready
    else [("Track", "Ready"), ("Dataset", "UCI 350"), ("Run", "08 + 09"), ("Model", "PySpark ML")]
)
credit_decision_note = (
    "The model excludes sex, education, marital status, and age. Its hypothetical review queue only demonstrates ranking and workload trade-offs; it is not an approval or decline recommendation."
    if credit_ready
    else "The UCI credit-default analysis is implemented but has not been run because the UCI dataset could not be downloaded in this execution environment. The downloader and analysis scripts are included."
)


def render_cards(cards: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'<div class="metric"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
        for label, value in cards
    )


html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Card Risk Analytics | Model Monitoring</title>
<style>
:root {{ color-scheme: light; --ink:#17243b; --muted:#64748b; --line:#e1e7ef; --paper:#f5f7fa; --blue:#1f4e79; --red:#b83b48; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 "Segoe UI",Arial,sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:38px 24px 56px; }}
header {{ border-radius:18px; padding:30px 34px; background:#142b4a; color:white; box-shadow:0 14px 36px #142b4a20; }}
.eyebrow {{ color:#b9cbe0; letter-spacing:.12em; text-transform:uppercase; font-size:12px; font-weight:700; }}
h1 {{ font-size:32px; margin:8px 0 6px; line-height:1.2; }}
header p {{ max-width:780px; color:#d7e2ef; margin:0; }}
section {{ margin-top:28px; }}
h2 {{ font-size:21px; margin:0 0 12px; }}
.sub {{ color:var(--muted); margin:-5px 0 16px; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
.metric,.panel,.note {{ background:white; border:1px solid var(--line); border-radius:14px; }}
.metric {{ padding:17px 18px; }}
.metric span {{ display:block; color:var(--muted); font-size:13px; }}
.metric strong {{ display:block; margin-top:7px; font-size:25px; color:var(--blue); }}
.panel {{ padding:14px; }}
.panel img {{ display:block; width:100%; height:auto; }}
.note {{ padding:18px 20px; color:#3e4e64; }}
.note strong {{ color:var(--ink); }}
.foot {{ color:var(--muted); font-size:12px; border-top:1px solid var(--line); margin-top:30px; padding-top:16px; }}
@media(max-width:760px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} main {{ padding:18px 14px 36px; }} header {{ padding:24px; }} h1 {{ font-size:27px; }} }}
</style>
</head>
<body><main>
<header><div class="eyebrow">Portfolio project · PySpark risk analytics</div>
<h1>Card Risk Monitoring</h1>
<p>Two distinct analytics tracks: transaction fraud triage and account-level default risk review. The metrics below come from untouched test/holdout samples; review flags are analytical scenarios, not production decisions.</p></header>

<section><h2>Transaction fraud</h2><p class="sub">Time-ordered evaluation · threshold {fraud_metrics['selected_threshold']:.2f} selected using validation data</p>
<div class="grid">{render_cards(fraud_cards)}</div></section>

<section><h2>Credit default risk</h2><p class="sub">Seeded train / validation / test split · review capacity set to 20% on validation scores</p>
<div class="grid">{render_cards(credit_cards)}</div></section>

<section><h2>Score separation and risk ranking</h2><div class="panel"><img alt="Fraud score distributions and default rate by test risk decile" src="data:image/png;base64,{chart}"></div></section>

<section><h2>Decision context</h2><div class="note">
<p><strong>Fraud:</strong> {fraud_metrics['true_positives']:,} fraud transactions were flagged, with {fraud_metrics['false_positives']:,} legitimate transactions also sent to review. Precision and recall describe this benchmark and threshold only.</p>
<p><strong>Credit:</strong> {credit_decision_note}</p>
<p><strong>Data limits:</strong> ULB fraud records are anonymized and span a short historical period. The UCI default benchmark represents a historical Taiwan bank snapshot. Neither dataset represents American Express customers, operating data, or current U.S. credit policy.</p>
</div></section>

<div class="foot">Generated locally from Spark model outputs. Fraud score and credit risk score are ranking signals and have not been calibrated as real-world probabilities. No customer-identifying records are embedded in this report.</div>
</main></body></html>"""

REPORT_DIR.mkdir(parents=True, exist_ok=True)
dashboard_path = REPORT_DIR / "risk_analytics_dashboard.html"
dashboard_path.write_text(html_doc, encoding="utf-8")
print(f"Dashboard written to: {dashboard_path}")
