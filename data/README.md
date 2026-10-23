# Data placement and provenance

Raw data and generated data are local-only and are excluded from Git by `.gitignore`.

## Transaction fraud

- Source: [ULB Credit Card Fraud Detection (Kaggle)](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud)
- Expected local path: `data/creditcard.csv`
- Dataset columns include `Time`, `V1`–`V28`, `Amount`, and `Class`.

The raw CSV is present in the development workspace but is not tracked. Download it from Kaggle yourself or use Kaggle’s permitted download flow; check the dataset page for current terms.

## Credit default

- Source: [UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)
- UCI ID: 350
- DOI: [10.24432/C55S3H](https://doi.org/10.24432/C55S3H)
- License listed by UCI: CC BY 4.0
- Download/normalized file: `data/raw/uci_credit_default.csv`
- Provenance record: `data/raw/uci_credit_default_source.json`

Run `src/08_download_credit_default.py` to fetch the dataset through UCI’s `ucimlrepo` package, normalize the columns, and record the download time and source metadata. The dataset describes historical credit outcomes at a Taiwan bank, not American Express customers.

## Generated outputs

Spark analysis outputs go under `data/processed/`. The scripts create CSV and JSON using local Python I/O after Spark computation, avoiding Spark’s local Hadoop file writer on Windows. These files are also excluded from Git.
