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
| `export_daily_report.py` | Build `historical-reports/YYYY-MM-DD.csv` (+ `latest.csv`) and refresh `reports.json` |
| `historical-reports/` | Dated full-universe CSVs (repo source of truth) |
| `` | GitHub Pages site (`index.html` dashboard + mirrored CSVs) |
| `RULES.md` | Screening / drawing / reporting rules |

## Daily report columns

`ticker, status, reason, current_price, entry, sl, tp, rr, zone_lo, zone_hi, atr, short_float_pct, inst_own_pct, dollar_vol_30d, avg_vol_30d, weekly_bars, days_to_earnings, earnings_known, earnings_blackout, smooth_pullback, weekly_reversal, weekly_reversal_kind, smooth_and_reversal, daily_reversal, daily_reversal_kind, smooth_streak, smooth_streak_weeks, tradingview_url`

## Export after a screen run

```bash
python export_daily_report.py \
  --results /workspace/stock_screen_results.csv \
  --verify /workspace/stock_screen_verify.csv \
  --date YYYY-MM-DD \
  --out-dir ./historical-reports \
  --docs-dir ./
```

The export also fills **`smooth_streak`** (short float < 5% AND ≥ `MIN_SMOOTH_STREAK_WEEKS` consecutive smooth weekly candles; default **5**; smooth week = green, red with weekly vol < 30w SMA, a weekly reversal shape, or a doji with body ≤ 10% of range and close ≥ low + 40% of range) and **`smooth_streak_weeks`** for every row from `/workspace/hist_cache.pkl`. Change the threshold in `/workspace/smooth_support_analysis.py` (`MIN_SMOOTH_STREAK_WEEKS`) or per run with `--min-smooth-streak-weeks N`. Backfill an existing CSV: `python /workspace/smooth_support_analysis.py --smooth-streak historical-reports/latest.csv`.

See `RULES.md` § Reports for the full process.
