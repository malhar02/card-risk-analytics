from pathlib import Path
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    avg,
    col,
    count,
    expr,
    max as spark_max,
    round as spark_round,
    when,
)

project_root = Path(__file__).resolve().parents[1]
csv_path = project_root / "data" / "creditcard.csv"

spark = (
    SparkSession.builder
    .master("local[*]")
    .appName("CardRiskFraudProfile")
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

row_count = df.count()
fraud_count = df.filter(col("Class") == 1).count()

print(f"Rows: {row_count:,}")
print(f"Fraud transactions: {fraud_count:,}")
print(f"Fraud rate: {fraud_count / row_count * 100:.3f}%")

print("Null values by column:")
df.select(
    *[count(when(col(name).isNull(), 1)).alias(name) for name in df.columns]
).show(truncate=False)

print("Amount summary by fraud label:")
(
    df.groupBy("Class")
    .agg(
        count("*").alias("transaction_count"),
        spark_round(avg("Amount"), 2).alias("average_amount"),
        spark_round(expr("percentile_approx(Amount, 0.5)"), 2).alias("median_amount"),
        spark_round(spark_max("Amount"), 2).alias("maximum_amount"),
    )
    .orderBy("Class")
    .show()
)

spark.stop()