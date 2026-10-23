"""Train a time-ordered fraud baseline and export review-ready holdout scores."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pyspark.ml import Pipeline
from pyspark.ml.classification import LogisticRegression
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import StandardScaler, VectorAssembler
from pyspark.ml.functions import vector_to_array
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, lit, when


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "creditcard.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
SELECTED_THRESHOLD = 0.80
THRESHOLDS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]


def safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def write_spark_csv(dataframe, path: Path) -> None:
    """Stream a small local Spark result to CSV without Hadoop's Windows writer."""
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(dataframe.columns)
        for row in dataframe.toLocalIterator():
            writer.writerow(row)


def write_records_csv(records: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


if not DATA_PATH.exists():
    raise FileNotFoundError(
        f"Fraud dataset not found at {DATA_PATH}. Place the Kaggle file at data/creditcard.csv."
    )

spark = (
    SparkSession.builder.master("local[*]")
    .appName("CardRiskFraudThresholdValidation")
    .config("spark.sql.shuffle.partitions", "4")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("ERROR")

try:
    df = (
        spark.read.option("header", "true")
        .option("inferSchema", "true")
        .csv(str(DATA_PATH))
    )

    required = {"Time", "Amount", "Class", *[f"V{i}" for i in range(1, 29)]}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"Fraud CSV is missing required columns: {missing}")

    # Keep the latest 30% of the timeline untouched until final evaluation.
    holdout_cutoff = df.approxQuantile("Time", [0.70], 0.001)[0]
    development_df = df.filter(col("Time") <= holdout_cutoff)
    validation_cutoff = development_df.approxQuantile("Time", [0.80], 0.001)[0]

    train_df = (
        development_df.filter(col("Time") <= validation_cutoff)
        .withColumn("label", col("Class").cast("double"))
    )
    validation_df = (
        development_df.filter(col("Time") > validation_cutoff)
        .withColumn("label", col("Class").cast("double"))
    )
    holdout_df = (
        df.filter(col("Time") > holdout_cutoff)
        .withColumn("label", col("Class").cast("double"))
    )

    class_counts = {
        int(row["Class"]): row["count"]
        for row in train_df.groupBy("Class").count().collect()
    }
    if class_counts.get(0, 0) == 0 or class_counts.get(1, 0) == 0:
        raise ValueError("Training split must contain both fraud and non-fraud rows.")
    fraud_weight = class_counts[0] / class_counts[1]
    train_df = train_df.withColumn(
        "class_weight", when(col("Class") == 1, lit(fraud_weight)).otherwise(lit(1.0))
    )

    feature_cols = ["Time", *[f"V{i}" for i in range(1, 29)], "Amount"]
    pipeline = Pipeline(
        stages=[
            VectorAssembler(inputCols=feature_cols, outputCol="raw_features"),
            StandardScaler(
                inputCol="raw_features",
                outputCol="features",
                withStd=True,
                withMean=True,
            ),
            LogisticRegression(
                featuresCol="features",
                labelCol="label",
                weightCol="class_weight",
                maxIter=50,
                regParam=0.01,
            ),
        ]
    )

    print(f"Training fraud weight: {fraud_weight:.1f}")
    model = pipeline.fit(train_df)

    validation_scored = (
        model.transform(validation_df)
        .withColumn("fraud_score", vector_to_array(col("probability"))[1])
        .cache()
    )
    validation_pr_auc = BinaryClassificationEvaluator(
        labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR"
    ).evaluate(validation_scored)

    print(f"Validation PR AUC: {validation_pr_auc:.4f}")
    print("Threshold | Alerts | TP | FP | FN | Precision | Recall")
    threshold_rows = []
    for threshold in THRESHOLDS:
        result = validation_scored.agg(
            count(when((col("label") == 1.0) & (col("fraud_score") >= threshold), 1)).alias("tp"),
            count(when((col("label") == 0.0) & (col("fraud_score") >= threshold), 1)).alias("fp"),
            count(when((col("label") == 1.0) & (col("fraud_score") < threshold), 1)).alias("fn"),
        ).first()
        tp, fp, fn = result["tp"], result["fp"], result["fn"]
        precision = safe_ratio(tp, tp + fp)
        recall = safe_ratio(tp, tp + fn)
        threshold_rows.append(
            {
                "threshold": threshold,
                "alerts": tp + fp,
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": fn,
                "precision": precision,
                "recall": recall,
            }
        )
        print(
            f"{threshold:9.2f} | {tp + fp:6,} | {tp:2,} | {fp:2,} | {fn:2,} "
            f"| {precision:9.3f} | {recall:6.3f}"
        )

    holdout_scored = (
        model.transform(holdout_df)
        .withColumn("fraud_score", vector_to_array(col("probability"))[1])
        .withColumn(
            "model_flag",
            (col("fraud_score") >= lit(SELECTED_THRESHOLD)).cast("int"),
        )
        .cache()
    )
    holdout_pr_auc = BinaryClassificationEvaluator(
        labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR"
    ).evaluate(holdout_scored)
    holdout_roc_auc = BinaryClassificationEvaluator(
        labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC"
    ).evaluate(holdout_scored)

    counts = holdout_scored.agg(
        count("*").alias("transactions"),
        count(when(col("label") == 1.0, 1)).alias("fraud_transactions"),
        count(when((col("label") == 1.0) & (col("model_flag") == 1), 1)).alias("tp"),
        count(when((col("label") == 0.0) & (col("model_flag") == 1), 1)).alias("fp"),
        count(when((col("label") == 1.0) & (col("model_flag") == 0), 1)).alias("fn"),
    ).first()
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    alerts = tp + fp

    print(f"\nFinal holdout results at threshold {SELECTED_THRESHOLD:.2f}:")
    print(f"PR AUC: {holdout_pr_auc:.4f}")
    print(f"ROC AUC: {holdout_roc_auc:.4f}")
    print(f"TP: {tp:,} | FP: {fp:,} | FN: {fn:,} | Alerts: {alerts:,}")
    print(f"Precision: {precision:.3f}")
    print(f"Recall: {recall:.3f}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scores_path = OUTPUT_DIR / "fraud_holdout_scores.csv"
    score_columns = [
        col("Time").alias("elapsed_seconds"),
        col("Amount"),
        col("Class").alias("actual_fraud"),
        col("fraud_score"),
        col("model_flag"),
    ]
    # Stream local results through Python's CSV writer to avoid Hadoop/winutils
    # when Spark writes files on Windows.
    write_spark_csv(holdout_scored.select(*score_columns), scores_path)
    write_records_csv(threshold_rows, OUTPUT_DIR / "fraud_validation_thresholds.csv")

    metrics = {
        "dataset": "ULB/Kaggle Credit Card Fraud Detection",
        "train_rows": int(sum(class_counts.values()) + 0),
        "fraud_weight": float(fraud_weight),
        "validation_pr_auc": float(validation_pr_auc),
        "holdout_rows": int(counts["transactions"]),
        "holdout_fraud_rows": int(counts["fraud_transactions"]),
        "selected_threshold": SELECTED_THRESHOLD,
        "threshold_selection_note": "0.80 selected from validation trade-offs before final holdout evaluation; score is not calibrated probability.",
        "holdout_pr_auc": float(holdout_pr_auc),
        "holdout_roc_auc": float(holdout_roc_auc),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "alerts": int(alerts),
        "precision": float(precision),
        "recall": float(recall),
        "score_file": str(scores_path.relative_to(PROJECT_ROOT)),
    }
    (OUTPUT_DIR / "fraud_model_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    print(f"Dashboard scores saved to: {scores_path}")
    print(f"Metrics saved to: {OUTPUT_DIR / 'fraud_model_metrics.json'}")

    validation_scored.unpersist()
    holdout_scored.unpersist()
finally:
    spark.stop()
