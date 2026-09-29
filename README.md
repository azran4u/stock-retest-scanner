# stock-retest-scanner

Weekly retest stock screener maintained with Grok Bot for Eyal.

## Live dashboard (GitHub Pages)

**https://azran4u.github.io/stock-retest-scanner/**

- Loads full-universe daily CSVs from `historical-reports/`
- Summary cards; per-filter pass-count chart (click toggles), R:R and smooth-streak distributions of the current selection
- One checkbox per filter (ANDed); nothing checked = full FinViz list; live “N of M stocks”; PASS-equivalent preset
- Sortable table of **all** FinViz tickers

## Layout

| Path | Purpose |
|------|---------|
| `stock_screen.py` | FinViz + yfinance screener |
| `report_filters.py` | Standalone per-row filters (`f_*`), CONFIG + CLI overrides, cache-only backfill |
| `export_daily_report.py` | Build `historical-reports/YYYY-MM-DD.csv` (+ `latest.csv`) and refresh `reports.json` |
| `historical-reports/` | Dated full-universe CSVs (repo source of truth) |
| `` | GitHub Pages site (`index.html` dashboard + mirrored CSVs) |
| `RULES.md` | Screening / drawing / reporting rules |

## Daily report columns

Every FinViz row, every filter computed independently (`report_filters.py`):

| Filter | Rule |
|---|---|
| `f_dollar_vol` | 30d avg dollar volume ≥ $50M |
| `f_short_float` | short float < 5% |
| `f_no_earnings_14d` | next earnings not within 14 days (unknown → false) |
| `f_history` | ≥ 150 weekly bars (~3y) |
| `f_rr` | retest setup (zone → entry/SL/TP) computed AND R:R ≥ 2 — one filter |
| `f_smooth_streak` | ≥ 5 consecutive smooth weekly candles |
| `f_weekly_reversal` | reversal-shape weekly candle in last 5 completed weeks |
| `f_daily_reversal` | reversal-shape daily candle in last 10 completed sessions |

`status=PASS` = `f_dollar_vol AND f_short_float AND f_no_earnings_14d AND f_history AND f_rr` (Grok watchlist). Value columns: `dollar_vol_30d, short_float_pct, earnings_date, days_to_earnings, weekly_bars, rr, entry, sl, tp, zone_lo, zone_hi, sl_atr_mult, smooth_streak_weeks, weekly/daily_reversal_kind/_date`, plus `failed_filters`, `filter_notes`, `smooth_pullback`, links and `reason`.

## Export after a screen run

```bash
python export_daily_report.py \
  --results /workspace/stock_screen_results.csv \
  --verify /workspace/stock_screen_verify.csv \
  --date YYYY-MM-DD \
  --out-dir ./historical-reports \
  --docs-dir ./
```

The export computes all filter columns for every row, sets `status`, and writes the Grok target (`/workspace/stock-screener/grok_sync_target.{json,txt}`). All thresholds/lookbacks are in `report_filters.py` `CONFIG`; each is a CLI flag on the export and on `report_filters.py` (e.g. `--min-smooth-streak-weeks 6`, `--daily-reversal-lookback-days 5`). Recompute an existing report from cache: `python report_filters.py --report historical-reports/latest.csv --date YYYY-MM-DD`.

See `RULES.md` § Reports for the full process.
