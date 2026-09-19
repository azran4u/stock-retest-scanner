# stock-retest-scanner

Weekly retest stock screener maintained with Grok Bot for Eyal.

## Live dashboard (GitHub Pages)

**https://azran4u.github.io/stock-retest-scanner/**

- Loads full-universe daily CSVs from `historical-reports/`
- Summary cards, PASS/FAIL charts, fail-reason buckets, R:R distribution
- Sortable / filterable table of **all** FinViz tickers (not only PASSes)

## Layout

| Path | Purpose |
|------|---------|
| `stock_screen.py` | FinViz + yfinance screener |
| `export_daily_report.py` | Build `historical-reports/YYYY-MM-DD.csv` (+ `latest.csv`) and refresh `docs/reports.json` |
| `historical-reports/` | Dated full-universe CSVs (repo source of truth) |
| `docs/` | GitHub Pages site (`index.html` dashboard + mirrored CSVs) |
| `RULES.md` | Screening / drawing / reporting rules |

## Daily report columns

`ticker, status, reason, current_price, entry, sl, tp, rr, zone_lo, zone_hi, atr, short_float_pct, inst_own_pct, dollar_vol_30d, avg_vol_30d, weekly_bars, days_to_earnings, earnings_known, earnings_blackout, tradingview_url`

## Export after a screen run

```bash
python export_daily_report.py \
  --results /workspace/stock_screen_results.csv \
  --verify /workspace/stock_screen_verify.csv \
  --date YYYY-MM-DD \
  --out-dir ./historical-reports \
  --docs-dir ./docs
```

See `RULES.md` § Reports for the full process.
