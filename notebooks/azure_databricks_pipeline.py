# Databricks notebook source
# Card Risk Analytics — Azure Databricks / PySpark implementation
#
# Before running: upload the two CSVs to a Unity Catalog Volume and grant the
# notebook identity read access to that volume and create/write access to the
# target catalog schema. This notebook contains no storage account keys.

# COMMAND ----------

from pyspark.ml import Pipeline
from pyspark.ml.classification import LogisticRegression
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import StandardScaler, VectorAssembler
from pyspark.ml.functions import vector_to_array
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType
import re

dbutils.widgets.text("raw_volume_root", "", "Unity Catalog volume root")
dbutils.widgets.text("target_catalog_schema", "", "Target catalog.schema")

raw_root = dbutils.widgets.get("raw_volume_root").strip().rstrip("/")
target = dbutils.widgets.get("target_catalog_schema").strip()

if not raw_root.startswith("/Volumes/"):
    raise ValueError(
        "Set raw_volume_root to the Unity Catalog Volume path, for example "
        "/Volumes/<catalog>/<schema>/<volume>/raw"
    )
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", target):
    raise ValueError("target_catalog_schema must be a valid catalog.schema identifier.")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {target}")

fraud_path = f"{raw_root}/fraud/creditcard.csv"
credit_path = f"{raw_root}/credit_default/uci_credit_default.csv"

fraud_source = (
    spark.read.option("header", "true").option("inferSchema", "true").csv(fraud_path)
)
credit_source = (
    spark.read.option("header", "true").option("inferSchema", "true").csv(credit_path)
)

fraud_features = [f"V{i}" for i in range(1, 29)]
credit_features = [
    "LIMIT_BAL", "PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6",
    "BILL_AMT1", "BILL_AMT2", "BILL_AMT3", "BILL_AMT4", "BILL_AMT5", "BILL_AMT6",
    "PAY_AMT1", "PAY_AMT2", "PAY_AMT3", "PAY_AMT4", "PAY_AMT5", "PAY_AMT6",
]

# COMMAND ----------

# Validate and curate transaction fraud data as a managed Delta table.
required_fraud = {"Time", "Amount", "Class", *fraud_features}
missing_fraud = sorted(required_fraud.difference(fraud_source.columns))
if missing_fraud:
    raise ValueError(f"Fraud CSV is missing required columns: {missing_fraud}")
if fraud_source.filter(F.col("Class").isNull() | ~F.col("Class").isin(0, 1)).limit(1).count():
    raise ValueError("Fraud Class must be non-null and binary.")

fraud_silver = fraud_source.select(
    F.col("Time").cast("double").alias("elapsed_seconds"),
    F.col("Amount").cast("double").alias("amount"),
    F.col("Class").cast("int").alias("is_fraud"),
    *[F.col(name).cast("double").alias(name.lower()) for name in fraud_features],
).withColumn("elapsed_hour", F.floor(F.col("elapsed_seconds") / 3600).cast("int"))

fraud_table = f"{target}.fraud_transactions_silver"
fraud_silver.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(fraud_table)
display(spark.table(fraud_table).groupBy("is_fraud").count().orderBy("is_fraud"))

# COMMAND ----------

# Curate the credit default benchmark. Demographic columns are excluded from the
# model table and from model features; this is a learning benchmark, not policy.
credit_required = set(credit_features + ["default_payment_next_month"])
missing_credit = sorted(credit_required.difference(credit_source.columns))
if missing_credit:
    raise ValueError(f"Credit default CSV is missing required columns: {missing_credit}")
if credit_source.filter(
    F.col("default_payment_next_month").isNull()
    | ~F.col("default_payment_next_month").isin(0, 1)
).limit(1).count():
    raise ValueError("Credit default target must be non-null and binary.")

credit_silver = credit_source.select(
    *[F.col(name).cast("double").alias(name.lower()) for name in credit_features],
    F.col("default_payment_next_month").cast("int").alias("default_next_month"),
)
credit_table = f"{target}.credit_default_modeling_silver"
credit_silver.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(credit_table)
display(spark.table(credit_table).agg(
    F.count("*").alias("accounts"),
    F.avg("default_next_month").alias("observed_default_rate"),
))

# COMMAND ----------

# Fraud model: chronological train / validation / final holdout.
fraud = spark.table(fraud_table)
fraud_model_features = ["elapsed_seconds", "amount", *[name.lower() for name in fraud_features]]
fraud_cutoff = fraud.approxQuantile("elapsed_seconds", [0.70], 0.001)[0]
fraud_development = fraud.filter(F.col("elapsed_seconds") <= fraud_cutoff)
fraud_validation_cutoff = fraud_development.approxQuantile("elapsed_seconds", [0.80], 0.001)[0]

fraud_train = fraud_development.filter(F.col("elapsed_seconds") <= fraud_validation_cutoff).withColumn("label", F.col("is_fraud").cast("double"))
fraud_validation = fraud_development.filter(F.col("elapsed_seconds") > fraud_validation_cutoff).withColumn("label", F.col("is_fraud").cast("double"))
fraud_holdout = fraud.filter(F.col("elapsed_seconds") > fraud_cutoff).withColumn("label", F.col("is_fraud").cast("double"))

fraud_counts = {int(row["is_fraud"]): row["count"] for row in fraud_train.groupBy("is_fraud").count().collect()}
fraud_weight = fraud_counts[0] / fraud_counts[1]
fraud_train = fraud_train.withColumn(
    "class_weight", F.when(F.col("is_fraud") == 1, F.lit(fraud_weight)).otherwise(F.lit(1.0))
)
fraud_pipeline = Pipeline(stages=[
    VectorAssembler(inputCols=fraud_model_features, outputCol="raw_features"),
    StandardScaler(inputCol="raw_features", outputCol="features", withStd=True, withMean=True),
    LogisticRegression(featuresCol="features", labelCol="label", weightCol="class_weight", maxIter=50, regParam=0.01),
])
fraud_model = fraud_pipeline.fit(fraud_train)
fraud_validation_scored = fraud_model.transform(fraud_validation).withColumn(
    "fraud_score", vector_to_array(F.col("probability"))[1]
)
threshold_rows = []
for threshold in [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]:
    counts = fraud_validation_scored.agg(
        F.sum(F.when((F.col("label") == 1) & (F.col("fraud_score") >= threshold), 1).otherwise(0)).alias("tp"),
        F.sum(F.when((F.col("label") == 0) & (F.col("fraud_score") >= threshold), 1).otherwise(0)).alias("fp"),
        F.sum(F.when((F.col("label") == 1) & (F.col("fraud_score") < threshold), 1).otherwise(0)).alias("fn"),
    ).first()
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    threshold_rows.append((threshold, tp + fp, tp, fp, fn,
                           tp / (tp + fp) if tp + fp else 0.0,
                           tp / (tp + fn) if tp + fn else 0.0))
threshold_schema = StructType([
    StructField("threshold", DoubleType(), False),
    StructField("alerts", LongType(), False),
    StructField("true_positives", LongType(), False),
    StructField("false_positives", LongType(), False),
    StructField("false_negatives", LongType(), False),
    StructField("precision", DoubleType(), False),
    StructField("recall", DoubleType(), False),
])
threshold_df = (
    spark.createDataFrame(threshold_rows, threshold_schema)
    .withColumn("risk_domain", F.lit("Fraud"))
)
display(threshold_df)
fraud_thresholds_table = f"{target}.fraud_dashboard_thresholds"
threshold_df.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true"
).saveAsTable(fraud_thresholds_table)

# Threshold 0.80 follows the local validation exercise. Review it against the
# validation queue-size table before adopting any operational capacity target.
fraud_threshold = 0.80
fraud_test_scored = (
    fraud_model.transform(fraud_holdout)
    .withColumn("fraud_score", vector_to_array(F.col("probability"))[1])
    .withColumn("model_flag", (F.col("fraud_score") >= F.lit(fraud_threshold)).cast("int"))
)
fraud_pr_auc = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR").evaluate(fraud_test_scored)
fraud_roc_auc = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC").evaluate(fraud_test_scored)
display(fraud_test_scored.agg(
    F.count("*").alias("transactions"),
    F.sum(F.when((F.col("label") == 1) & (F.col("model_flag") == 1), 1).otherwise(0)).alias("true_positives"),
    F.sum(F.when((F.col("label") == 0) & (F.col("model_flag") == 1), 1).otherwise(0)).alias("false_positives"),
    F.sum(F.when((F.col("label") == 1) & (F.col("model_flag") == 0), 1).otherwise(0)).alias("false_negatives"),
    F.lit(fraud_pr_auc).alias("holdout_pr_auc"),
))
fraud_scores_table = f"{target}.fraud_holdout_scores"
fraud_test_scored.select("elapsed_seconds", "amount", "is_fraud", "fraud_score", "model_flag").write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(fraud_scores_table)

# COMMAND ----------

# Credit model: seeded random split because the UCI benchmark has no event date.
# The validation 80th percentile sets a hypothetical 20% manual-review capacity.
credit = spark.table(credit_table)
credit_features_lower = [name.lower() for name in credit_features]
credit_model_data = credit.select(
    *credit_features_lower,
    F.col("default_next_month").cast("double").alias("label"),
)
credit_train, credit_validation, credit_test = credit_model_data.randomSplit([0.70, 0.15, 0.15], seed=42)
credit_pipeline = Pipeline(stages=[
    VectorAssembler(inputCols=credit_features_lower, outputCol="raw_features"),
    StandardScaler(inputCol="raw_features", outputCol="features", withStd=True, withMean=True),
    LogisticRegression(featuresCol="features", labelCol="label", maxIter=100, regParam=0.01),
])
credit_model = credit_pipeline.fit(credit_train)
credit_validation_scored = credit_model.transform(credit_validation).withColumn(
    "risk_score", vector_to_array(F.col("probability"))[1]
)
credit_threshold = credit_validation_scored.approxQuantile("risk_score", [0.80], 0.001)[0]
credit_test_scored = (
    credit_model.transform(credit_test)
    .withColumn("risk_score", vector_to_array(F.col("probability"))[1])
    .withColumn("review_flag", (F.col("risk_score") >= F.lit(credit_threshold)).cast("int"))
    .withColumn("risk_decile", F.ntile(10).over(Window.orderBy(F.col("risk_score").desc())))
)
credit_pr_auc = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR").evaluate(credit_test_scored)
credit_roc_auc = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC").evaluate(credit_test_scored)
display(credit_test_scored.agg(
    F.count("*").alias("accounts"),
    F.avg("label").alias("observed_default_rate"),
    F.avg("review_flag").alias("review_rate"),
    F.sum(F.when((F.col("label") == 1) & (F.col("review_flag") == 1), 1).otherwise(0)).alias("defaults_captured"),
    F.sum(F.when((F.col("label") == 0) & (F.col("review_flag") == 1), 1).otherwise(0)).alias("false_alerts"),
    F.lit(credit_pr_auc).alias("test_pr_auc"),
    F.lit(credit_roc_auc).alias("test_roc_auc"),
))
credit_scores_table = f"{target}.credit_default_test_scores"
credit_test_scored.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(credit_scores_table)

# COMMAND ----------

# Gold serving tables for Power BI. These tables contain aggregate benchmark
# results and risk segments; they do not expose source-row identifiers.
def safe_ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else 0.0


fraud_test_counts = fraud_test_scored.agg(
    F.count("*").alias("records"),
    F.sum("is_fraud").alias("observed_events"),
    F.sum("model_flag").alias("review_alerts"),
    F.sum(F.when((F.col("is_fraud") == 1) & (F.col("model_flag") == 1), 1).otherwise(0)).alias("true_positives"),
    F.sum(F.when((F.col("is_fraud") == 0) & (F.col("model_flag") == 1), 1).otherwise(0)).alias("false_positives"),
    F.sum(F.when((F.col("is_fraud") == 1) & (F.col("model_flag") == 0), 1).otherwise(0)).alias("false_negatives"),
).first()

credit_test_counts = credit_test_scored.agg(
    F.count("*").alias("records"),
    F.sum(F.col("label").cast("long")).alias("observed_events"),
    F.sum("review_flag").alias("review_alerts"),
    F.sum(F.when((F.col("label") == 1) & (F.col("review_flag") == 1), 1).otherwise(0)).alias("true_positives"),
    F.sum(F.when((F.col("label") == 0) & (F.col("review_flag") == 1), 1).otherwise(0)).alias("false_positives"),
    F.sum(F.when((F.col("label") == 1) & (F.col("review_flag") == 0), 1).otherwise(0)).alias("false_negatives"),
).first()

dashboard_summary_schema = StructType([
    StructField("risk_domain", StringType(), False),
    StructField("sample_name", StringType(), False),
    StructField("records", LongType(), False),
    StructField("observed_events", LongType(), False),
    StructField("review_alerts", LongType(), False),
    StructField("true_positives", LongType(), False),
    StructField("false_positives", LongType(), False),
    StructField("false_negatives", LongType(), False),
    StructField("precision", DoubleType(), False),
    StructField("recall", DoubleType(), False),
    StructField("observed_event_rate", DoubleType(), False),
    StructField("review_rate", DoubleType(), False),
    StructField("pr_auc", DoubleType(), False),
    StructField("roc_auc", DoubleType(), False),
    StructField("decision_cutoff", DoubleType(), False),
    StructField("decision_policy", StringType(), False),
])

def dashboard_summary_row(domain, sample_name, metrics, pr_auc, roc_auc, cutoff, policy):
    records = int(metrics["records"] or 0)
    events = int(metrics["observed_events"] or 0)
    alerts = int(metrics["review_alerts"] or 0)
    true_positives = int(metrics["true_positives"] or 0)
    false_positives = int(metrics["false_positives"] or 0)
    false_negatives = int(metrics["false_negatives"] or 0)
    return (
        domain, sample_name, records, events, alerts, true_positives,
        false_positives, false_negatives,
        safe_ratio(true_positives, alerts),
        safe_ratio(true_positives, true_positives + false_negatives),
        safe_ratio(events, records), safe_ratio(alerts, records),
        float(pr_auc), float(roc_auc), float(cutoff), policy,
    )


risk_summary_rows = [
    dashboard_summary_row(
        "Fraud", "Later-time holdout", fraud_test_counts,
        fraud_pr_auc, fraud_roc_auc, fraud_threshold,
        "Fixed 0.80 score cutoff from the validation exercise; score is not calibrated.",
    ),
    dashboard_summary_row(
        "Credit Default", "Seeded random test split", credit_test_counts,
        credit_pr_auc, credit_roc_auc, credit_threshold,
        "Validation-set 80th percentile cutoff for a hypothetical review queue.",
    ),
]
risk_summary_table = f"{target}.risk_dashboard_summary"
spark.createDataFrame(risk_summary_rows, dashboard_summary_schema).write.format("delta").mode(
    "overwrite"
).option("overwriteSchema", "true").saveAsTable(risk_summary_table)

domain_schema = StructType([
    StructField("risk_domain", StringType(), False),
    StructField("dataset_context", StringType(), False),
])
domain_rows = [
    ("Fraud", "Public ULB/Kaggle benchmark; anonymized features; time-based holdout; not Amex data."),
    ("Credit Default", "Historical UCI Taiwan bank benchmark; seeded random split; not U.S. lending data."),
]
domain_table = f"{target}.risk_dashboard_domain"
spark.createDataFrame(domain_rows, domain_schema).write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true"
).saveAsTable(domain_table)

fraud_hourly_table = f"{target}.fraud_dashboard_hourly"
(fraud_test_scored
 .withColumn("elapsed_dataset_hour", F.floor(F.col("elapsed_seconds") / 3600).cast("long"))
 .groupBy("elapsed_dataset_hour")
 .agg(
     F.count("*").alias("transaction_count"),
     F.sum("is_fraud").alias("fraud_count"),
     F.sum("model_flag").alias("alert_count"),
     F.sum(F.when((F.col("is_fraud") == 1) & (F.col("model_flag") == 1), 1).otherwise(0)).alias("captured_fraud_count"),
     F.avg("fraud_score").alias("average_fraud_score"),
     F.sum("amount").alias("total_amount"),
 )
 .withColumn("risk_domain", F.lit("Fraud"))
 .write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(fraud_hourly_table))

credit_deciles_table = f"{target}.credit_dashboard_deciles"
(credit_test_scored
 .groupBy("risk_decile")
 .agg(
     F.count("*").alias("account_count"),
     F.sum(F.col("label").cast("long")).alias("default_count"),
     F.avg("label").alias("observed_default_rate"),
     F.avg("risk_score").alias("average_risk_score"),
     F.sum("review_flag").alias("reviewed_account_count"),
 )
 .withColumn("risk_domain", F.lit("Credit Default"))
 .write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(credit_deciles_table))

credit_status_table = f"{target}.credit_dashboard_payment_status"
(credit_test_scored
 .groupBy("pay_0")
 .agg(
     F.count("*").alias("account_count"),
     F.sum(F.col("label").cast("long")).alias("default_count"),
     F.avg("label").alias("observed_default_rate"),
     F.avg("risk_score").alias("average_risk_score"),
     F.sum("review_flag").alias("reviewed_account_count"),
 )
 .withColumnRenamed("pay_0", "latest_payment_status_code")
 .withColumn("risk_domain", F.lit("Credit Default"))
 .write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(credit_status_table))

print("Curated, scored, and Power BI serving Delta tables:")
print(f"  {fraud_table}")
print(f"  {fraud_scores_table}")
print(f"  {credit_table}")
print(f"  {credit_scores_table}")
print(f"  {risk_summary_table}")
print(f"  {domain_table}")
print(f"  {fraud_thresholds_table}")
print(f"  {fraud_hourly_table}")
print(f"  {credit_deciles_table}")
print(f"  {credit_status_table}")
