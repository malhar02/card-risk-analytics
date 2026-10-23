CARD RISK ANALYTICS — POWER BI IMPORT KIT

This folder contains six model-ready CSV tables generated from the completed
local benchmark outputs, a Power BI theme, the Azure Databricks notebook and
setup guide, and a static HTML dashboard preview.

LOCAL POWER BI IMPORT
1. In Power BI Desktop, choose Home > Get data > Text/CSV.
2. Import the six CSV files in this folder.
3. In Model view, create one-to-many, single-direction relationships from
   risk_dashboard_domain[risk_domain] to risk_domain in each other table.
4. Apply powerbi_theme.json through View > Themes > Browse for themes.
5. Follow POWER_BI_AZURE_GUIDE.md for DAX measures and page layouts.

CLOUD-CONNECTED VERSION
The CSVs are local snapshots. For cloud integration, run the included
Azure Databricks notebook and connect Power BI to its Unity Catalog Delta
serving tables through a Databricks SQL warehouse, as described in the guide.

This package does not contain a signed-in .pbix file. Power BI Desktop and
your Microsoft/Azure account are needed to create and publish that report.
The public Kaggle/UCI benchmarks are not Amex data and do not represent
Amex production performance.
