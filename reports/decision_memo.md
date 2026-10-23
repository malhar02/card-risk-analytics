# Card Risk Analytics — Decision Memo

**Run date:** 2026-10-23  
**Purpose:** Demonstrate how a card-risk analyst can evaluate model ranking quality alongside review workload.  
**Audience:** Risk analytics / fraud operations interview discussion.

## Executive readout

The fraud baseline ranks a small, highly imbalanced holdout usefully, but the selected threshold still sends many legitimate transactions to review. The credit-default baseline separates the riskiest accounts from the rest of this historical benchmark, while its 20% review queue captures about half of the test defaults. Both results support risk prioritization as an analytics workflow; neither supports automated real-customer decisions.

## Transaction fraud

The analysis used a chronological split: the earliest 56% of transactions for model fit, the next 14% for threshold review, and the latest 30% as the untouched holdout. A class-weighted logistic regression used elapsed time, amount, and anonymized `V1`–`V28` variables. The threshold was set to 0.80 from validation trade-offs before the final holdout scoring.

| Holdout measure | Result |
|---|---:|
| Transactions / fraud labels | 85,500 / 108 |
| PR AUC | 0.5318 |
| ROC AUC | 0.9788 |
| Alerts at threshold 0.80 | 313 |
| Fraud flagged (true positives) | 89 |
| Legitimate transactions flagged (false positives) | 224 |
| Missed fraud (false negatives) | 19 |
| Precision / recall | 28.4% / 82.4% |

**Operational reading:** this threshold captures 82.4% of holdout fraud labels while creating 224 false alerts for investigation. A higher threshold reduces queue volume but misses more fraud; a lower threshold drives recall up while making the review queue much larger. The validation table is saved as `data/processed/fraud_validation_thresholds.csv`.

## Credit default risk

The UCI sample contains 30,000 accounts and no event date, so the script uses a seeded 70% / 15% / 15% random train, validation, and test split. A standardized, unweighted logistic regression uses credit limit, repayment history, statement balances, and payment amounts. Sex, education, marital status, and age are excluded from model features. The validation 80th-percentile score defines a hypothetical 20% manual-review capacity; that score cutoff is then evaluated on the test set.

| Test measure | Result |
|---|---:|
| Accounts / defaults | 4,464 / 1,004 |
| Observed default rate | 22.5% |
| PR AUC / ROC AUC | 0.5062 / 0.7116 |
| Accounts routed to review | 918 (20.6%) |
| Defaults in review queue | 506 of 1,004 (50.4% capture) |
| False alerts / missed defaults | 412 / 498 |
| Review precision | 55.1% |

**Segmentation read:** the highest risk decile has a 70.0% observed default rate, compared with 22.5% overall in the test set. Deciles 2 and 3 are 41.4% and 18.6%; the remaining deciles are noisier. The output is a ranking score and is not calibrated as a real-world probability of loss.

## Recommendation for a real operating discussion

Treat the models as prioritization prototypes. The next analyst conversation should begin with the team’s review capacity and the relative costs of missed fraud, false alerts, and delayed customer decisions. Thresholds should be chosen on validation data against those agreed operating goals, then evaluated once on a later, representative holdout. Before deployment, add current product and behavior data, probability calibration, temporal and segment monitoring, explainability, fairness/legal review, and human oversight.

## Portfolio framing

> I built two independent PySpark risk workflows: a time-ordered fraud triage model and a credit-default review analysis. I focused on severe class imbalance, validation-only threshold selection, out-of-sample workload metrics, risk deciles, and clear benchmark limitations. The fraud test captured 82% of fraud at 28% precision, while a 20% credit review queue captured 50% of defaults in the UCI holdout. The project is structured for an Azure Databricks and Unity Catalog workflow, but the cloud resources are not provisioned.

## Important data limits

- The ULB fraud sample uses anonymized features and a short historical period. It lacks customer, merchant, device, and richer payment-network context.
- The UCI default benchmark is a historical Taiwan bank snapshot, not Amex or current U.S. lending data. Its random split does not test temporal generalization.
- A flagged transaction is not necessarily confirmed fraud, and a default label does not determine the correct credit action.
- The model scores are not calibrated probabilities. Review flags are illustrative workload scenarios only.

## Provenance

- Fraud source: [ULB Credit Card Fraud Detection dataset](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud).
- Credit source and license: [UCI Default of Credit Card Clients, DOI 10.24432/C55S3H](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients), CC BY 4.0.
