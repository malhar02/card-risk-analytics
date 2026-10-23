from pathlib import Path
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, sum as spark_sum, when

project_root = Path(__file__).resolve().parents[1]
csv_path = project_root / "data" / "creditcard.csv"

spark = (
    SparkSession.builder
    .master("local[*]")
    .appName("CardRiskTimeSplit")
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
print(f"70% time cutoff: {cutoff:.2f} seconds")

train_df = df.filter(col("Time") <= cutoff)
test_df = df.filter(col("Time") > cutoff)

def show_split_summary(name, split_df):
    result = split_df.agg(
        count("*").alias("transactions"),
        spark_sum(when(col("Class") == 1, 1).otherwise(0)).alias("fraud_transactions"),
    ).first()

    transactions = result["transactions"]
    frauds = result["fraud_transactions"] or 0
    fraud_rate = frauds / transactions * 100

    print(
        f"{name}: {transactions:,} transactions, "
        f"{frauds:,} frauds, {fraud_rate:.3f}% fraud"
    )

show_split_summary("Train", train_df)
show_split_summary("Holdout", test_df)

spark.stop()