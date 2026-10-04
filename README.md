# stock-retest-scanner

Weekly retest stock screener maintained with Grok Bot for Eyal.

## Live dashboard (GitHub Pages)

**https://azran4u.github.io/stock-retest-scanner/** — main dashboard = TradingView chart gallery (`index.html`, since 2026-10-04)
**https://azran4u.github.io/stock-retest-scanner/table.html** — full report table (secondary page; nav links between both; old `charts.html` links redirect to `index.html`)

Report table (`table.html`):
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
| `index.html` | GitHub Pages main dashboard: TradingView chart gallery |
| `table.html` | Report table (filters, charts, sortable table of all tickers) |
| `charts.html` | Redirect to `index.html` (old links) |
| `RULES.md` | Screening / drawing / reporting rules |

## Daily report columns

Every FinViz row, every filter computed independently (`report_filters.py`):

| Filter | Rule |
|---|---|
| `f_dollar_vol` | 30d avg dollar volume ≥ $50M |
| `f_short_float` | short float < 5% |
| `f_no_earnings_14d` | next earnings not within 14 days (unknown → false) |
| `f_history` | ≥ 150 weekly bars (~3y) |
| `f_rr` | TradingView drawing found AND TV R:R (`tv_rr`) ≥ 2; not found → False (old computed flag kept internally as `f_rr_computed`, not part of status) |
| `f_smooth_streak` | ≥ 5 consecutive smooth weekly candles |
| `f_weekly_reversal` | reversal-shape weekly candle in last 5 completed weeks |
| `f_daily_reversal` | reversal-shape daily candle in last 10 completed sessions |
| `f_near_zone` | TV drawings only (else empty): latest daily close within 1 × weekly ATR(14) of the TV zone (0 inside it); values `tv_price`, `tv_weekly_atr`, `tv_zone_dist`, `tv_zone_dist_atr`. Informational — not part of status / Grok target; refreshed by the nightly export and `tv_drawings.py merge` |
| `needs_drawing` | $vol + short float + no earnings ≤14d + history pass AND no TradingView drawing (not found or never read) → `grok_needs_drawing_target.{json,txt}` (daily export + `tv_drawings.py merge`). Not part of status / `grok_sync_target` |
| `f_tv_stale`, `tv_stale`, `tv_stale_detail` | TV drawings only: drawing may be obsolete — `broken` (any price below the drawn SL since the read date — any daily low/intraday wick < SL by default, `--close-basis daily|weekly` for closes; below the zone but above SL does not count), `target hit` (latest close ≥ TP), `far` (latest close > zone top + 3 weekly ATR). Informational — not part of status. `python tv_drawings.py stale` → `tv_stale.json` (+ `/workspace/stock-screener/tv_stale.{json,csv}`); also refreshed by the export and `merge` |

`status=PASS` = `f_dollar_vol AND f_short_float AND f_no_earnings_14d AND f_history AND f_rr` (Grok watchlist), with `f_rr` = TradingView drawing found AND TV R:R ≥ 2 — a missing drawing fails.

**TradingView drawings (source of truth for zone / entry / SL / TP / R:R, read-only — never modify the drawings):** `tv_drawings.py targets` writes the daily read list (`/workspace/tv_read_targets.{txt,json}`: dollar vol + short float + live no-earnings-14d + history; no smooth-streak requirement); `tv_drawings.py upsert NYSE:ST --zone-top 41.96 --zone-bottom 41.31 --entry 42.11 --sl 38.46 --tp 51.55 --rr 2.59` (or `--not-found`) records a read in `/workspace/stock-screener/tv_drawings.json`; `tv_drawings.py merge` adds `tv_found, tv_zone_top, tv_zone_bottom, tv_entry, tv_sl, tv_tp, tv_rr, tv_read_date` (latest reading per ticker) to the report, recomputes `status` and regenerates `grok_sync_target.{json,txt}` (the nightly screen/export read `tv_drawings.json` directly). The dashboard shows only these TV values (“not found” when there is no drawing); computed geometry is hidden. Value columns: `dollar_vol_30d, short_float_pct, earnings_date, days_to_earnings, weekly_bars, rr, entry, sl, tp, zone_lo, zone_hi, sl_atr_mult, smooth_streak_weeks, weekly/daily_reversal_kind/_date`, plus `failed_filters`, `filter_notes`, `smooth_pullback`, links and `reason`.

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

## TradingView chart gallery — main dashboard (`index.html`)

Cards for every ticker with a read TradingView drawing (`tv_found=yes`), plus read-but-not-found tickers that have a screenshot (badge "needs drawing", no R:R): chart screenshot (click to enlarge), status, TV R:R, zone, entry / SL / TP, distance to zone (ATR), read date; sort R:R desc; toggles PASS only / near zone only / drawing may be obsolete (saved in localStorage); red badge + banner (from `tv_stale.json`) for drawings that may be obsolete. Screenshots: `python tv_drawings.py upsert NYSE:ST …values… --screenshot /workspace/tv_shots/ST.png` → `charts/latest/ST.webp` (≤1280px, <300KB, overwritten each read; CSV column `tv_screenshot`); not-found reads too: `upsert NYSE:XYZ --not-found --screenshot /workspace/tv_shots/XYZ.png`. Cards without an image show "screenshot after next nightly read".

## Position sizing (client-side)

The chart gallery (`index.html`) and the report table (`table.html`) share a settings bar (Account $, Max risk %, Max position %; defaults 5000 / 1 / 15; saved in localStorage). For tickers with a TradingView drawing: `shares = floor(min(account·risk%/(entry−SL), account·pos%/entry))` (0 if entry ≤ SL) → columns Shares, Cost, Risk $, Profit at TP $ (+ limiting cap); blank without a drawing; recalculated live (`sizing.js`). Filters "tradable with account" (shares ≥ 1) / "not tradable (account limits)" (drawn, shares = 0) on both pages.
