from pathlib import Path
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col,
    count,
    floor,
    round as spark_round,
    sum as spark_sum,
    when,
)

project_root = Path(__file__).resolve().parents[1]
csv_path = project_root / "data" / "creditcard.csv"

spark = (
    SparkSession.builder
    .master("local[*]")
    .appName("CardRiskFraudMonitoring")
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

is_flagged = when(col("Class") == 1, 1).otherwise(0)
flagged_amount = when(col("Class") == 1, col("Amount")).otherwise(0)

print("Overall monitoring metrics:")
df.agg(
    count("*").alias("transactions"),
    spark_sum(is_flagged).alias("flagged_transactions"),
    spark_round(spark_sum(is_flagged) / count("*") * 100, 3).alias("flagged_rate_pct"),
    spark_round(spark_sum("Amount"), 2).alias("gross_transaction_amount"),
    spark_round(spark_sum(flagged_amount), 2).alias("flagged_transaction_amount"),
    spark_round(
        spark_sum(flagged_amount) / spark_sum("Amount") * 100, 3
    ).alias("flagged_amount_share_pct"),
).show(truncate=False)

print("Metrics by elapsed hour:")
hourly = (
    df.withColumn("elapsed_hour", floor(col("Time") / 3600).cast("int"))
    .groupBy("elapsed_hour")
    .agg(
        count("*").alias("transactions"),
        spark_sum(is_flagged).alias("flagged_transactions"),
        spark_sum(flagged_amount).alias("flagged_transaction_amount"),
    )
    .withColumn(
        "flagged_rate_pct",
        spark_round(col("flagged_transactions") / col("transactions") * 100, 3),
    )
    .orderBy("elapsed_hour")
)

hourly.show(100, truncate=False)
spark.stop()