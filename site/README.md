# Card Risk Intelligence dashboard

This static interactive dashboard is designed for GitHub Pages. It reads only data/dashboard.json, a compact set of precomputed aggregates. No account-level transaction or credit records are included in the published website.

## Features

- Overview across the independent fraud and credit-default model tracks.
- Validation threshold explorer for fraud, with a separate final holdout readout.
- Clickable fraud activity buckets and credit risk deciles.
- Credit repayment-status segment explorer with small-sample warnings.
- Searchable, sortable aggregate tables with CSV and JSON downloads.
- Methodology, benchmark provenance, and model-use limitations.

## Rebuild the data snapshot

From the project root, run:

python scripts/build_dashboard_data.py

The script reads the six aggregate CSV files under reports/powerbi_dashboard_kit/ and writes site/data/dashboard.json.

## Run locally

Open the project root in VS Code and run a local static server, or use GitHub Pages after deployment. The page uses a relative JSON fetch, so opening index.html directly through a file:// URL is not supported by modern browser security.
