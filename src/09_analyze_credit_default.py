"""Build a leakage-aware credit default risk baseline with PySpark ML."""

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
from pyspark.sql.functions import avg, col, count, lit, ntile, when
from pyspark.sql.window import Window


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "raw" / "uci_credit_default.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
TARGET = "default_payment_next_month"
FEATURES = [
    "LIMIT_BAL",
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
AUDIT_ONLY_COLUMNS = ["SEX", "EDUCATION", "MARRIAGE", "AGE"]
REVIEW_CAPACITY = 0.20
SEED = 42


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
        f"Credit dataset not found at {DATA_PATH}. First run src/08_download_credit_default.py."
    )

spark = (
    SparkSession.builder.master("local[*]")
    .appName("CardRiskCreditDefaultBaseline")
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
    required = set(FEATURES + AUDIT_ONLY_COLUMNS + [TARGET])
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"Credit default CSV is missing required columns: {missing}")

    invalid_targets = df.filter(~col(TARGET).isin(0, 1)).limit(1).count()
    if invalid_targets:
        raise ValueError(f"Target {TARGET} must contain only 0 and 1.")
    nulls = df.select(
        *[count(when(col(name).isNull(), 1)).alias(name) for name in FEATURES + [TARGET]]
    ).first().asDict()
    nonzero_nulls = {name: value for name, value in nulls.items() if value}
    if nonzero_nulls:
        raise ValueError(f"Nulls found in model inputs or target: {nonzero_nulls}")

    # This dataset has no event date, so use a deterministic seeded random split.
    # Demographic columns are deliberately excluded from model features and kept
    # out of score exports; this is an educational benchmark, not a lending policy.
    model_data = df.select(
        *[col(name).cast("double").alias(name) for name in FEATURES],
        col(TARGET).cast("double").alias("label"),
        col("PAY_0").cast("int").alias("audit_pay_0"),
        col("LIMIT_BAL").cast("double").alias("audit_limit_bal"),
        col("BILL_AMT1").cast("double").alias("audit_bill_amt1"),
    )
    train_df, validation_df, test_df = model_data.randomSplit(
        [0.70, 0.15, 0.15], seed=SEED
    )
    if min(train_df.count(), validation_df.count(), test_df.count()) == 0:
        raise ValueError("A train, validation, or test split is empty.")

    pipeline = Pipeline(
        stages=[
            VectorAssembler(inputCols=FEATURES, outputCol="raw_features"),
            StandardScaler(
                inputCol="raw_features",
                outputCol="features",
                withStd=True,
                withMean=True,
            ),
            LogisticRegression(
                featuresCol="features",
                labelCol="label",
                maxIter=100,
                regParam=0.01,
            ),
        ]
    )
    print("Fitting logistic regression on financial-behavior features only...")
    model = pipeline.fit(train_df)
    validation_scored = (
        model.transform(validation_df)
        .withColumn("risk_score", vector_to_array(col("probability"))[1])
        .cache()
    )

    # Route the riskiest 20% of the validation population to a hypothetical
    # manual review queue. This is a capacity scenario, not an approval cutoff.
    selected_threshold = validation_scored.approxQuantile(
        "risk_score", [1.0 - REVIEW_CAPACITY], 0.001
    )[0]
    threshold_rows = []
    print(f"Validation review-score cutoff for {REVIEW_CAPACITY:.0%} capacity: {selected_threshold:.4f}")
    print("Threshold | Review | Defaults captured | False alerts | Precision | Capture rate")
    for threshold in [0.10, 0.20, 0.30, 0.40, 0.50, selected_threshold]:
        result = validation_scored.agg(
            count(when((col("label") == 1.0) & (col("risk_score") >= threshold), 1)).alias("tp"),
            count(when((col("label") == 0.0) & (col("risk_score") >= threshold), 1)).alias("fp"),
            count(when((col("label") == 1.0) & (col("risk_score") < threshold), 1)).alias("fn"),
        ).first()
        tp, fp, fn = result["tp"], result["fp"], result["fn"]
        precision = safe_ratio(tp, tp + fp)
        capture = safe_ratio(tp, tp + fn)
        threshold_rows.append(
            {
                "threshold": float(threshold),
                "review_accounts": int(tp + fp),
                "defaults_captured": int(tp),
                "false_alerts": int(fp),
                "missed_defaults": int(fn),
                "precision": float(precision),
                "default_capture_rate": float(capture),
            }
        )
        print(
            f"{threshold:9.4f} | {tp + fp:6,} | {tp:17,} | {fp:12,} "
            f"| {precision:9.3f} | {capture:12.3f}"
        )

    test_scored = (
        model.transform(test_df)
        .withColumn("risk_score", vector_to_array(col("probability"))[1])
        .withColumn(
            "review_flag", (col("risk_score") >= lit(selected_threshold)).cast("int")
        )
        .withColumn(
            "risk_decile",
            ntile(10).over(Window.orderBy(col("risk_score").desc())),
        )
        .cache()
    )
    pr_auc = BinaryClassificationEvaluator(
        labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR"
    ).evaluate(test_scored)
    roc_auc = BinaryClassificationEvaluator(
        labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC"
    ).evaluate(test_scored)
    result = test_scored.agg(
        count("*").alias("accounts"),
        count(when(col("label") == 1.0, 1)).alias("defaults"),
        count(when((col("label") == 1.0) & (col("review_flag") == 1), 1)).alias("tp"),
        count(when((col("label") == 0.0) & (col("review_flag") == 1), 1)).alias("fp"),
        count(when((col("label") == 1.0) & (col("review_flag") == 0), 1)).alias("fn"),
    ).first()
    tp, fp, fn = result["tp"], result["fp"], result["fn"]
    precision = safe_ratio(tp, tp + fp)
    capture = safe_ratio(tp, tp + fn)
    review_rate = safe_ratio(tp + fp, result["accounts"])

    print("\nUntouched test-set results at the validation-selected review cutoff:")
    print(f"PR AUC: {pr_auc:.4f} | ROC AUC: {roc_auc:.4f}")
    print(
        f"Review queue: {tp + fp:,} ({review_rate:.1%}) | "
        f"defaults captured: {tp:,}/{result['defaults']:,} ({capture:.1%})"
    )
    print(f"False alerts: {fp:,} | Missed defaults: {fn:,} | Precision: {precision:.3f}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    score_path = OUTPUT_DIR / "credit_default_test_scores.csv"
    score_columns = [
        col("audit_limit_bal").alias("limit_balance"),
        col("audit_bill_amt1").alias("latest_statement_amount"),
        col("audit_pay_0").alias("latest_payment_status"),
        col("label").cast("int").alias("actual_default"),
        col("risk_score"),
        col("review_flag"),
        col("risk_decile"),
    ]
    # Stream local results through Python's CSV writer to avoid Hadoop/winutils
    # when Spark writes files on Windows.
    write_spark_csv(test_scored.select(*score_columns), score_path)
    unique_threshold_rows = list(
        {row["threshold"]: row for row in threshold_rows}.values()
    )
    write_records_csv(
        unique_threshold_rows, OUTPUT_DIR / "credit_default_validation_policy.csv"
    )

    deciles = (
        test_scored.groupBy("risk_decile")
        .agg(
            count("*").alias("accounts"),
            count(when(col("label") == 1.0, 1)).alias("defaults"),
            avg("label").alias("observed_default_rate"),
            avg("risk_score").alias("average_risk_score"),
        )
        .orderBy("risk_decile")
    )
    write_spark_csv(deciles, OUTPUT_DIR / "credit_default_deciles.csv")
    delinquency = (
        test_scored.groupBy("audit_pay_0")
        .agg(
            count("*").alias("accounts"),
            avg("label").alias("observed_default_rate"),
            avg("risk_score").alias("average_risk_score"),
        )
        .withColumnRenamed("audit_pay_0", "latest_payment_status")
        .orderBy("latest_payment_status")
    )
    write_spark_csv(
        delinquency, OUTPUT_DIR / "credit_default_delinquency_segments.csv"
    )

    metrics = {
        "dataset": "UCI Default of Credit Card Clients (Taiwan, historical snapshot)",
        "seed": SEED,
        "model": "Standardized logistic regression, unweighted",
        "model_features": FEATURES,
        "excluded_from_model": AUDIT_ONLY_COLUMNS,
        "threshold_policy": "Top 20% of validation risk scores routed to a hypothetical manual review queue; not an approval/decline rule.",
        "selected_review_threshold": float(selected_threshold),
        "validation_accounts": int(validation_scored.count()),
        "test_accounts": int(result["accounts"]),
        "test_defaults": int(result["defaults"]),
        "test_default_rate": safe_ratio(result["defaults"], result["accounts"]),
        "test_pr_auc": float(pr_auc),
        "test_roc_auc": float(roc_auc),
        "test_review_accounts": int(tp + fp),
        "test_review_rate": float(review_rate),
        "test_defaults_captured": int(tp),
        "test_false_alerts": int(fp),
        "test_missed_defaults": int(fn),
        "test_precision": float(precision),
        "test_default_capture_rate": float(capture),
        "risk_score_is_calibrated_probability": False,
        "score_file": str(score_path.relative_to(PROJECT_ROOT)),
    }
    (OUTPUT_DIR / "credit_default_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    print(f"Scored accounts saved to: {score_path}")

    validation_scored.unpersist()
    test_scored.unpersist()
finally:
    spark.stop()
