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
| `stock_screen.py` | FinViz + yfinance screener (`SCREENER_URL` = `https://finviz.com/screener?v=111&f=sh_instown_o60,sh_price_o10,sh_short_low,ta_sma200_pa,ta_sma50_pb&ft=4&o=ticker`: inst own > 60%, price > $10, short float low < 5%, above SMA200, below SMA50; since 2026-10-09) |
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
| `f_weekly_reversal` | reversal-shape weekly candle in last 5 completed weeks **at the TV zone** (low ≤ top + 0.5 weekly ATR and (low ≥ bottom − 0.5 ATR or close ≥ bottom); no zone → false) |
| `f_daily_reversal` | reversal-shape daily candle in last 10 completed sessions **at the TV zone** (same rule, daily ATR) |
| `f_near_zone` | TV drawings only (else empty): latest daily close within 1 × weekly ATR(14) of the TV zone (0 inside it); values `tv_price`, `tv_weekly_atr`, `tv_zone_dist`, `tv_zone_dist_atr`. Informational — not part of status / Grok target; refreshed by the nightly export and `tv_drawings.py merge` |
| `needs_drawing` | $vol + short float + no earnings ≤14d + history pass AND no TradingView drawing (not found or never read) → `grok_needs_drawing_target.{json,txt}` (daily export + `tv_drawings.py merge`). Not part of status / `grok_sync_target` |
| `f_tv_stale`, `tv_stale`, `tv_stale_detail` | TV drawings only: drawing may be obsolete — `broken` (any price below the drawn SL since the read date — any daily low/intraday wick < SL by default, `--close-basis daily|weekly` for closes; below the zone but above SL does not count), `target hit` (latest close ≥ TP), `far` (latest close > zone top + 3 weekly ATR). Informational — not part of status. `python tv_drawings.py stale` → `tv_stale.json` (+ `/workspace/stock-screener/tv_stale.{json,csv}`); also refreshed by the export and `merge` |
| `f_technical` (+ `tech_*`) | Clear weekly uptrend, every row with >=130 weekly bars: new 26w high >=1 ATR above the prior 2.5y high, >=50% higher highs/lows over 78w (strength-3 swings, current-pullback lows ignored), 30w EMA higher than 26w ago. Informational, not part of status |
| `tv_source`, `f_bot_review`, `tv_bot_status`, `tv_bot_note` | Drawing owner: user / bot / bot-approved. Bot drawings (registry `/workspace/stock-screener/bot_drawings.json`, matched by near-identical levels; `upsert --source bot` / rectangle text "BOT - review needed") are "review needed": **not** counted toward f_rr / PASS / Grok until approved (`python tv_drawings.py bot approve T` -> `approved_bot_drawings.json`); changed levels = user-owned. Excluded from `needs_drawing`. Bot drawings still review-needed within the read-target universe ($vol + short float + no earnings ≤14d + history) → `grok_review_target.{json,txt}` (TradingView watchlist `grok_review`; daily export + `tv_drawings.py merge`). Also `user-lines` (only Fib / horizontal lines: `upsert --not-found --lines-only`, not needs drawing) and partial user drawings (`upsert --partial --drawing-status …`) |
| `ev_first_reaction`, `ev_double_bottom`, `ev_ma_support` (+`_mas`), `ev_fib` (+`_levels`), `*_detail`, `ev_pullback_high(_date)` | Reversal evidence E3 / E4 / E7 / E8 for the grade (`report_filters.compute_evidence`; exact rules in `RULES.md` § "Grades A/B/C/D"). E3/E4/E8 need a TV zone. Informational, not part of status |

**Grades (browser, live):** a stock gets **A/B/C/D** only when all 9 **must-haves** pass — FinViz list, short float < 5%, no earnings ≤ **E** days (default 14), $vol ≥ **V** (default $50M), history ≥ 3y, tradable with the account, technical, price near zone, counted TV R:R ≥ 2 — else `-` with the failing must-haves shown. Evidence: E1 weekly reversal at the zone (5w), E2 daily reversal at the zone (10d), E3 first reaction, E4 daily double bottom, E5 smooth pullback ≥ **N** weeks (default 5), E6 TV R:R ≥ **X** (default 3), E7 MA support (SMA 50/100/150/200 that held before), E8 zone overlaps fib 0.382/0.5/0.618. A = all 8, B = 1 missing, C = 2, D = 3+. E / V / N / X are inputs on both pages (they also drive the earnings, $vol and smooth filters), with a **Must-haves** preset, grade / evidence filters, grade badges + evidence chips. Default sort: TV R:R desc. PASS / Grok are unchanged.

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

Cards for every ticker with a read TradingView drawing (`tv_found=yes`), plus read-but-not-found tickers that have a screenshot (badge "needs drawing", no R:R): chart screenshot (click to enlarge), status, TV R:R, zone, entry / SL / TP, distance to zone (ATR), read date; sort R:R desc; toggles PASS only / near zone only / technical / bot drawing (review needed) / drawing may be obsolete (saved in localStorage); bot drawings appear as cards (purple badge) even before the nightly read; red badge + banner (from `tv_stale.json`) for drawings that may be obsolete. Screenshots: `python tv_drawings.py upsert NYSE:ST …values… --screenshot /workspace/tv_shots/ST.png` → `charts/latest/ST.webp` (≤1280px, <300KB, overwritten each read; CSV column `tv_screenshot`); not-found reads too: `upsert NYSE:XYZ --not-found --screenshot /workspace/tv_shots/XYZ.png`. Cards without an image show "screenshot after next nightly read".

## Position sizing (client-side)

The chart gallery (`index.html`) and the report table (`table.html`) share a settings bar (Account $, Max risk %, Max position %; defaults 5000 / 1 / 15; saved in localStorage). For tickers with a TradingView drawing: `shares = floor(min(account·risk%/(entry−SL), account·pos%/entry))` (0 if entry ≤ SL) → columns Shares, Cost, Risk $, Profit at TP $ (+ limiting cap); blank without a drawing; recalculated live (`sizing.js`). Filters "tradable with account" (shares ≥ 1) / "not tradable (account limits)" (drawn, shares = 0) on both pages.
