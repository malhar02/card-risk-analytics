from pyspark.sql import SparkSession
from pyspark.sql.functions import avg, count, round

spark = (
    SparkSession.builder
    .master("local[*]")
    .appName("CardRiskAnalytics")
    .config("spark.sql.shuffle.partitions", "4")
    .getOrCreate()
)

transactions = [
    ("TX001", "C001", 12.50, 0),
    ("TX002", "C001", 840.00, 1),
    ("TX003", "C002", 34.20, 0),
    ("TX004", "C002", 11.80, 0),
    ("TX005", "C003", 620.00, 1),
    ("TX006", "C004", 52.00, 0),
    ("TX007", "C003", 19.40, 0),
    ("TX008", "C005", 1150.00, 1),
]

columns = ["transaction_id", "customer_id", "amount", "is_fraud"]
df = spark.createDataFrame(transactions, schema=columns)

print("Sample transactions:")
df.show()

print("Transaction summary by fraud label:")
(
    df.groupBy("is_fraud")
    .agg(
        count("*").alias("transaction_count"),
        round(avg("amount"), 2).alias("average_amount"),
    )
    .orderBy("is_fraud")
    .show()
)

spark.stop()