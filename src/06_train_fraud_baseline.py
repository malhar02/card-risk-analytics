from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, lit, when
from pyspark.ml import Pipeline
from pyspark.ml.classification import LogisticRegression
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import StandardScaler, VectorAssembler

project_root = Path(__file__).resolve().parents[1]
csv_path = project_root / "data" / "creditcard.csv"

spark = (
    SparkSession.builder
    .master("local[*]")
    .appName("CardRiskWeightedLogisticBaseline")
    .config("spark.sql.shuffle.partitions", "4")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("ERROR")

df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .csv(str(csv_path))
)

cutoff = df.approxQuantile("Time", [0.70], 0.001)[0]

train_df = (
    df.filter(col("Time") <= cutoff)
    .withColumn("label", col("Class").cast("double"))
)
holdout_df = (
    df.filter(col("Time") > cutoff)
    .withColumn("label", col("Class").cast("double"))
)

class_counts = {
    int(row["Class"]): row["count"]
    for row in train_df.groupBy("Class").count().collect()
}
fraud_weight = class_counts[0] / class_counts[1]

train_df = train_df.withColumn(
    "class_weight",
    when(col("Class") == 1, lit(fraud_weight)).otherwise(lit(1.0)),
)

feature_cols = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount"]

assembler = VectorAssembler(
    inputCols=feature_cols,
    outputCol="raw_features",
)

scaler = StandardScaler(
    inputCol="raw_features",
    outputCol="features",
    withStd=True,
    withMean=True,
)

classifier = LogisticRegression(
    featuresCol="features",
    labelCol="label",
    weightCol="class_weight",
    maxIter=50,
    regParam=0.01,
)

pipeline = Pipeline(stages=[assembler, scaler, classifier])

print(f"Training fraud weight: {fraud_weight:.1f}")
model = pipeline.fit(train_df)
predictions = model.transform(holdout_df)

pr_auc = BinaryClassificationEvaluator(
    labelCol="label",
    rawPredictionCol="rawPrediction",
    metricName="areaUnderPR",
).evaluate(predictions)

roc_auc = BinaryClassificationEvaluator(
    labelCol="label",
    rawPredictionCol="rawPrediction",
    metricName="areaUnderROC",
).evaluate(predictions)

print(f"Holdout PR AUC: {pr_auc:.4f}")
print(f"Holdout ROC AUC: {roc_auc:.4f}")
print("Confusion matrix at Spark's default 0.5 threshold:")
predictions.groupBy("label", "prediction").count().orderBy(
    "label", "prediction"
).show()

counts = predictions.agg(
    count(when((col("label") == 1.0) & (col("prediction") == 1.0), 1)).alias("tp"),
    count(when((col("label") == 0.0) & (col("prediction") == 1.0), 1)).alias("fp"),
    count(when((col("label") == 1.0) & (col("prediction") == 0.0), 1)).alias("fn"),
).first()

tp = counts["tp"]
fp = counts["fp"]
fn = counts["fn"]

precision = tp / (tp + fp) if tp + fp else 0.0
recall = tp / (tp + fn) if tp + fn else 0.0

print(f"Precision at 0.5 threshold: {precision:.3f}")
print(f"Recall at 0.5 threshold: {recall:.3f}")

spark.stop()