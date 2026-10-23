from pathlib import Path
from pyspark.sql import SparkSession

project_root = Path(__file__).resolve().parents[1]
csv_path = project_root / "data" / "creditcard.csv"

if not csv_path.exists():
    raise FileNotFoundError(f"Dataset not found: {csv_path}")

spark = (
    SparkSession.builder
    .master("local[*]")
    .appName("CardRiskFraudDataLoad")
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

print("Dataset schema:")
df.printSchema()

print(f"Total rows: {df.count():,}")
print("Transactions by fraud label:")
df.groupBy("Class").count().orderBy("Class").show()

spark.stop()