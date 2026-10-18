# Panda Sellout Intelligence

Standalone dashboard and detailed reports for the last eight completed weekly wholesale allocations. This project is independent of Bamboo SKU Intelligence.

- GitHub: https://github.com/robertmckinley-alt/Pandasellout
- Production: https://pandasellout.vercel.app
- Source: https://api-intelligence.getbamboo.com/api/reports/allocation-sell-through?limit=8

## Read the dashboard

Exact sellout means a positive, reconciled allocation with positive sales and no remaining units. Frequency is sold-out weeks divided by offered weeks. Coverage and units remain visible to distinguish repeated demand from small allocations. Charts, rankings, and the CSV follow the selected filters; Excel and PDF contain the full eight-week period.

Exclude trade samples, non-marijuana merchandise, zero/unlimited allocations, incomplete weeks, and invalid records from analysis. Preserve all original rows in `data/source.json` and the workbook. Source sold units include submitted and pending wholesale orders; they do not represent confirmed consumer retail purchases. The endpoint cannot establish day/time of sellout, physical retail stockouts, lost sales, or optimum price/production changes.

## Local use

Serve the project directory with `python -m http.server 8765 --bind 127.0.0.1`, then open http://127.0.0.1:8765. Stop the server when finished. No package installation or build is required for the dashboard. React/Babel are version-pinned CDN dependencies; a network connection is required.

## Refresh and checks

The GitHub workflow runs Mondays at 15:30 UTC (08:30 PDT / 07:30 PST) and supports manual dispatch. It fetches the latest eight periods, validates rules, refreshes the formatted workbook, rebuilds PDF/CSVs, and commits only generated data/reports. Vercel deploys `main` through its Git integration. Failed workflows leave the last good snapshot published; source freshness is visible on the dashboard.

```
python scripts/refresh_sell_through.py
python -m unittest discover -s scripts -p test_sell_through.py
python scripts/refresh_workbook.py
python scripts/build_report.py
python scripts/validate_release.py
```

PDF generation requires ReportLab (`reportlab==4.4.4` is used in CI). `refresh_workbook.py` uses the Python standard library to refresh the existing artifact-authored workbook, preserving styles and native charts. The original JS authoring script needs the documented bundled artifact-tool dependency; normal weekly refreshes do not.

Downloads: `Bamboo_Weekly_Sell_Through_8_Weeks.xlsx`, `Bamboo_Sellout_Report_8_Weeks.pdf`, full product rankings CSV, and eligible weekly detail CSV. Dashboard CSV follows filters and exports product IDs.
