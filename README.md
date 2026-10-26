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
| `stock_screen.py` | FinViz + yfinance screener (`SCREENER_URL` = `https://finviz.com/screener?v=111&f=sh_price_o10,ta_sma50_pb&ft=4&o=ticker`: price > $10, below SMA50 (SMA200 dropped 2026-10-26); since 2026-10-14 — inst own / short float are collected per ticker (FinViz v=131 → yfinance) and are optional dashboard filters, not must-haves) |
| `report_filters.py` | Standalone per-row filters (`f_*`), CONFIG + CLI overrides, cache-only backfill |
| `export_daily_report.py` | Build `historical-reports/YYYY-MM-DD.csv` (+ `latest.csv`) and refresh `reports.json` |
| `historical-reports/` | Dated full-universe CSVs (repo source of truth) |
| `index.html` | GitHub Pages main dashboard: TradingView chart gallery |
| `table.html` | Report table (filters, charts, sortable table of all tickers) |
| `charts.html` | Redirect to `index.html` (old links) |
| `RULES.md` | Screening / drawing / reporting rules |
| `fundamentals.py` / `fundamentals.js` / `analysis/analysis.json` | Fundamentals analysis for graded (A–D) tickers: sector, business, recent news, pros / cons, take — collapsible on chart cards, expandable row in the table. Manual refresh (web research, not nightly): `python fundamentals.py status` → `scaffold T` → `merge analysis/drafts/T.json` (RULES.md § 15) |

## Daily report columns

Every FinViz row, every filter computed independently (`report_filters.py`):

| Filter | Rule |
|---|---|
| `f_dollar_vol` | 30d avg dollar volume ≥ $50M |
| `f_short_float` | short float < 5% — informational (empty = unknown), not in status |
| `f_inst_own` | inst own ≥ 60% — informational (empty = unknown) |
| `f_no_earnings_14d` | next earnings not within 14 days (unknown → false) |
| `f_history` | ≥ 150 weekly bars (~3y) |
| `f_rr` | TradingView drawing found AND TV R:R (`tv_rr`) ≥ 2; not found → False (old computed flag kept internally as `f_rr_computed`, not part of status) |
| `f_no_red_vol_week` | info only since 2026-10-26 (core/WAIT 2026-10-23): last completed weekly candle (complete after Fri 16:30 NY) is NOT a healthy red bar (close < open, body ≥ 50% of range) on above-average volume (week avg daily vol > avg daily vol of the 30 trading days before the week). Only failure → `status=WAIT` (app: “ממתינה לסגירה”); next weekly close resolves it. Values `red_vol_week_date`, `red_vol_body_pct`, `red_vol_ratio`, `red_vol_detail` |
| `f_smooth_streak` | ≥ 5 consecutive smooth weekly candles |
| `f_weekly_reversal` | reversal-shape weekly candle in last 5 completed weeks **at the TV zone** (low ≤ top + 0.5 weekly ATR and (low ≥ bottom − 0.5 ATR or close ≥ bottom); no zone → false) |
| `f_daily_reversal` | reversal-shape daily candle in last 10 completed sessions **at the TV zone** (same rule, daily ATR) |
| `f_near_zone` | TV drawings only (else empty): latest daily close within 1 × weekly ATR(14) of the TV zone (0 inside it); values `tv_price`, `tv_weekly_atr`, `tv_zone_dist`, `tv_zone_dist_atr`. Informational — not part of status / Grok target; refreshed by the nightly export and `tv_drawings.py merge` |
| `needs_drawing` | $vol + no earnings ≤14d + history pass AND technical (after user overrides; since 2026-10-09) AND no TradingView drawing (not found, never read, or a bot drawing the user rejected — `tv_drawings.py bot reject T --note …`) → `grok_needs_drawing_target.{json,txt}` (daily export + `tv_drawings.py merge`). Not part of status / `grok_sync_target` |
| `f_tv_stale`, `tv_stale`, `tv_stale_detail` | TV drawings only: drawing may be obsolete — `broken` (any price below the drawn SL since the read date — any daily low/intraday wick < SL by default, `--close-basis daily|weekly` for closes; below the zone but above SL does not count), `target hit` (latest close ≥ TP), `far` (latest close > zone top + 3 weekly ATR). Informational — not part of status. `python tv_drawings.py stale` → `tv_stale.json` (+ `/workspace/stock-screener/tv_stale.{json,csv}`); also refreshed by the export and `merge`. Every flagged drawing (in or out of today's screen) → `/workspace/stock-screener/grok_obsolete_target.{json,txt}` (TradingView watchlist `grok_obsolete`) |
| `f_technical` (+ `tech_*`) | User override first (`/workspace/stock-screener/user_overrides.json`, `technical: false` → “not technical (Eyal)”, computed value in `tech_computed`, excluded from needs drawing / `grok_review`). Otherwise (v2, 2026-10-09): clear weekly uptrend = recent 26w high ≥ prior 2.5y high − 1 weekly ATR AND 30w EMA up ≥ 8% in 26 weeks (rejects sideways; tuned on Eyal's calls, see RULES.md). Informational, not part of status |
| `tv_source`, `f_bot_review`, `tv_bot_status`, `tv_bot_note` | Drawing owner: user / bot / bot-approved. Bot drawings (registry `/workspace/stock-screener/bot_drawings.json`, matched by near-identical levels; `upsert --source bot` / rectangle text "BOT - review needed") are "review needed": **not** counted toward f_rr / PASS / Grok until approved (`python tv_drawings.py bot approve T` -> `approved_bot_drawings.json`); changed levels = user-owned. Excluded from `needs_drawing`. Bot drawings still review-needed within the read-target universe ($vol + short float + no earnings ≤14d + history) → `grok_review_target.{json,txt}` (TradingView watchlist `grok_review`; daily export + `tv_drawings.py merge`). Also `user-lines` (only Fib / horizontal lines: `upsert --not-found --lines-only`, not needs drawing) and partial user drawings (`upsert --partial --drawing-status …`) |
| `ev_first_reaction`, `ev_double_bottom`, `ev_ma_support` (+`_mas`), `ev_fib` (+`_levels`), `*_detail`, `ev_pullback_high(_date)` | Reversal evidence E3 / E4 / E7 / E8 for the grade (`report_filters.compute_evidence`; exact rules in `RULES.md` § "Grades A/B/C/D"). E3/E4/E8 need a TV zone. Informational, not part of status |

**Grades (browser, live):** a stock gets **A/B/C/D** only when all 8 **must-haves** pass (short float removed 2026-10-14) — FinViz list, no earnings ≤ **E** days (default 14), $vol ≥ **V** (default $50M), history ≥ 3y, tradable with the account, technical, price near zone, counted TV R:R ≥ 2 — else `-` with the failing must-haves shown. Evidence: E1 weekly reversal at the zone (5w), E2 daily reversal at the zone (10d), E3 first reaction, E4 daily double bottom, E5 smooth pullback ≥ **N** weeks (default 5), E6 TV R:R ≥ **X** (default 3), E7 MA support (SMA 50/100/150/200 that held before), E8 zone overlaps fib 0.382/0.5/0.618. A = all 8, B = 1 missing, C = 2, D = 3+. E / V / N / X are inputs on both pages (they also drive the earnings, $vol and smooth filters), with a **Must-haves** preset, grade / evidence filters, grade badges + evidence chips. Default sort: TV R:R desc. PASS / Grok are unchanged.

`status=PASS` = `f_dollar_vol AND f_no_earnings_14d AND f_history AND f_rr AND f_from_above` (Grok watchlist; else FAIL — WAIT cancelled 2026-10-26, `f_no_red_vol_week` / `f_no_inv_hammer` are info only; no earnings date in any of TradingView / Yahoo / Nasdaq = passes the earnings gate), with `f_rr` = TradingView drawing found AND TV R:R ≥ 2 — a missing drawing fails.

**TradingView drawings (source of truth for zone / entry / SL / TP / R:R, read-only — never modify the drawings):** `tv_drawings.py targets` writes the daily read list (`/workspace/tv_read_targets.{txt,json}`: dollar vol + live no-earnings-14d + history; no smooth-streak requirement); `tv_drawings.py upsert NYSE:ST --zone-top 41.96 --zone-bottom 41.31 --entry 42.11 --sl 38.46 --tp 51.55 --rr 2.59` (or `--not-found`) records a read in `/workspace/stock-screener/tv_drawings.json`; `tv_drawings.py merge` adds `tv_found, tv_zone_top, tv_zone_bottom, tv_entry, tv_sl, tv_tp, tv_rr, tv_read_date` (latest reading per ticker) to the report, recomputes `status` and regenerates `grok_sync_target.{json,txt}` (the nightly screen/export read `tv_drawings.json` directly). The dashboard shows only these TV values (“not found” when there is no drawing); computed geometry is hidden. Value columns: `dollar_vol_30d, short_float_pct, earnings_date, days_to_earnings, weekly_bars, rr, entry, sl, tp, zone_lo, zone_hi, sl_atr_mult, smooth_streak_weeks, weekly/daily_reversal_kind/_date`, plus `failed_filters`, `filter_notes`, `smooth_pullback`, links and `reason`.

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

## Last-week hammer

**Last-week hammer (Eyal 2026-10-15, informational):** `f_last_week_reversal` / `last_week_reversal_kind` (`hammer (green)` / `hammer (red)`) / `last_week_date` = the **last completed** W-FRI weekly candle (not the current partial week; a Friday-after-close run includes that Friday's week, earlier weekdays use the previous Friday) is a **classic hammer, any colour** (Investopedia / TA-Lib CDLHAMMER-style; Eyal 2026-10-15; E1 keeps its own looser hammer): range > 0, lower shadow ≥ 2 × real body, real body in the upper third of the range (min(open, close) ≥ low + ⅔ × range), little or no upper shadow (≤ 10% of the range); the only extra is the tiny-doji exclusion (range < 0.2 × weekly ATR(14) and body < 0.05 × ATR) — **without** the zone-proximity gate. Strong close / engulfing / rejection do not count here (E1 unchanged). Computed by `report_filters.compute_reversals` for **every** FinViz row in every daily export (and `report_filters.py --report` recomputes). Dashboard: filter "last week hammer (no zone)" in Grade & evidence, green "last wk: hammer (…)" chip on cards, table columns. Not a must-have, not a grade item.

**Hammer gate (Eyal 2026-10-23):** a last-week hammer is only *surfaced* (app `hammer` badge / chip / list inclusion / hammer sort, and the dashboard's hammer-only cards) when the row also passes the must-haves `f_dollar_vol` AND `f_history` AND `f_no_earnings_14d` (same report columns; unknown earnings date = not passing). `f_last_week_reversal` and `hammer_*` columns themselves are unchanged (still computed for every row). Other inclusion reasons (PASS, needs drawing, review, obsolete, positions, TV/app drawings, watchlist) are not gated: a starred ticker still shows, just without the hammer badge. Code: `srs_app/export_data.hammer_ok`, `index.html hammerOk`.

## Last-week hammer trade

**Last-week hammer trade (Eyal 2026-10-15, informational):** for every row with `f_last_week_reversal` (classic hammer on the last completed week), computed daily for all FinViz rows by `report_filters.compute_hammer_trade`: `hammer_entry` = hammer week close; `hammer_sl` = hammer week low − `HAMMER_SL_ATR_BUFFER` (0.05) × weekly ATR(14); `hammer_tp` / `hammer_tp_date` = highest weekly **body** (max of open/close, not wicks) in the 52 weeks before the hammer week (hammer excluded); `hammer_rr` = (TP − entry) ÷ (entry − SL), empty with `hammer_no_room` = True when TP ≤ entry. `hammer_calm_weeks` = consecutive calm weeks going back from the week before the hammer (cap 104): green (close > open), OR red/flat with weekly volume < 30-week SMA of weekly volume (rolling, incl. that week — same as the smooth streak), OR a doji week of any colour/volume (body ≤ 10% of range — the smooth-streak doji without its close ≥ low + 40% condition, Eyal 2026-10-15), OR a loud red week that contains an earnings date (yfinance `get_earnings_dates`, cached `cache/earnhist_{T}.json` 30 days, failures retried after 1 day); unknown earnings → not calm, explained in `hammer_calm_note`. `hammer_score` = hammer_rr × ln(1 + calm weeks): R:R scaled by a slowly growing bonus for a calm pullback (0 calm weeks → 0; 5 weeks ×1.8; 15 weeks ×2.8); empty when no R:R. Dashboard: inputs H (hammer R:R, default 2) and C (calm weeks, default 5) → filters "hammer R:R ≥ H" and "calm weeks ≥ C" next to "last week hammer"; table columns; Charts sort options Hammer R:R / Calm weeks / Hammer score; with the hammer filter on, hammer rows without a TV drawing appear as cards (no screenshot, TradingView link, hammer levels); sizing uses the hammer entry/SL/TP for display when there is no TV drawing. Not a must-have, not a grade item.

## Position sizing (client-side)

**Tradable with account (Eyal 2026-10-15):** `f_tradable` = weekly ATR(14) per share (`weekly_atr`, CSV column for EVERY row — the same weekly ATR used for SL / near zone) **<** risk per trade = account × max risk % from the sizing bar (default $5000 × 1.1% = $55 since 2026-10-26; was 1% = $50), computed live in the browser (`filters.js` `sizingFlags`) for all FinViz rows, drawn or not. No weekly ATR (missing history) → unknown = not tradable. "not tradable" = ATR ≥ risk per trade. Shares / cost / risk / profit for drawn rows stay as info only. Must-have for the grade; not part of `status` / needs-drawing.

The chart gallery (`index.html`) and the report table (`table.html`) share a settings bar (Account $, Max risk %, Max position %; defaults 5000 / 1.1 / 15 (max risk $55 per trade since 2026-10-26; was 1% = $50); saved in localStorage). For tickers with a TradingView drawing: `shares = floor(min(account·risk%/(entry−SL), account·pos%/entry))` (0 if entry ≤ SL) → columns Shares, Cost, Risk $, Profit at TP $ (+ limiting cap); blank without a drawing; recalculated live (`sizing.js`). Filters "tradable with account" (shares ≥ 1) / "not tradable (account limits)" (drawn, shares = 0) on both pages.

## My positions (הפוזיציות שלי)

Open trades live in `positions.json` (repo root) and are shown at the top of `index.html` and `table.html`
(ticker → chart card, entry date, qty, entry, stop, target, latest close, P/L $ / %, R = (close − entry)/(entry − stop),
distance to stop / target in % and weekly ATR(14), chips: *near stop* / *near target* = daily low/high within 0.5 weekly ATR,
*stop hit* / *target hit*). Manage with `positions.py`:

```
/workspace/.venv/bin/python positions.py add TICKER --qty N --entry P --stop S [--target T] [--date YYYY-MM-DD] [--exchange NYSE]
/workspace/.venv/bin/python positions.py set TICKER --stop S --target T
/workspace/.venv/bin/python positions.py close TICKER --price P [--date ...]
/workspace/.venv/bin/python positions.py list | refresh | check [--no-refresh] [--json]
```

The daily export (`export_daily_report.py`) calls `positions.refresh()` (yfinance daily bar + weekly ATR) for open positions.
Alert routine: `/workspace/.venv/bin/python /workspace/stock-screener/positions_check.py` (exit 2 if any flag fires).
Default target = TP of the user's TradingView drawing (tv_drawings.json) at entry time.

**Web app positions bar (Eyal 2026-10-24).** Every app page (list + stock page, desktop + iPhone) has a fixed bar on top
with each open position: ticker (tap → stock page), qty × entry, current price, P/L $ (%), R = (price − entry)/(entry − SL),
SL and TP with the distance (level − price)/price, plus the total (Σ P/L $, Σ P/L / Σ cost %, Σ P/L / Σ risk R); green/red;
collapsible (localStorage `srs_posbar_collapsed`). Read-only: positions are managed with `positions.py` (chat), not in the app.
- *Storage / privacy:* Supabase `public.positions` (migration `positions_table`): RLS on, policy `owner_select` = SELECT for
  `authenticated` with JWT email azran4u@gmail.com (same rule as drawings / labels / watchlist); anon has no grant at all;
  no INSERT/UPDATE/DELETE grant for app users (written only by the bot's connector). In realtime publication.
- *Sync:* `positions.json` on the box stays the source of truth (the box has no Supabase key, so `positions.py` /
  `positions_check.py` keep reading the file). After any `add / set / close / refresh / check` (and after the daily export,
  which refreshes the market block), run the SQL printed by `python positions.py supabase-sql` with the Supabase connector
  (`execute_sql`, project wkkdblnykgolqijzagva): it upserts every position (open + closed, `raw` = the full JSON) and deletes
  rows no longer in the file. Test `tests/test_positions_supabase.py`.
- *Price* (`webapp/src/positions.ts`, polled every 60 s while visible, ↻ to refresh): CNBC quote API (real-time, CORS `*`)
  → if it fails, TradingView scanner (≈15 min delayed, labelled 'מושהה') → else the stored nightly close, labelled
  'סגירה אחרונה dd/mm'; no price → '—' (never invented). The label shows the quote time in Israel time ('CNBC 23/10 22:59
  (שעון ישראל)'), or 'CNBC · מחיר סגירה dd/mm' when CNBC only gives the date (after the close); pre/after-market last is
  shown next to the price (pre/AH) but P/L uses the regular-session price. Tests `test_positions.mjs`, `e2e_positions.mjs`.

**Stock overview 'סקירה' (Eyal 2026-10-24).** The stock page shows a collapsible 'סקירה' section for ANY ticker
with a row in Supabase `public.ticker_research` (owner-only RLS; not only starred): the bot's short Hebrew summary, one
topic per line (תחום / דוח אחרון / אנליסטים / חדשות / דוח הבא; the topic is bolded, Latin/number runs are bidi-isolated),
the update date (Israel time) and the source links. Open/closed is remembered. Rows are written by the bot (PASS
overviews: `data.scope = 'pass_overview'`, `data.news[]`; starred research), never by the app. Test: `e2e_research.mjs`.

## `srs` — deterministic building blocks (CLI + Python package)

Small pure functions with tests, runnable on any Mac/Linux. Separate from the daily scan
(`stock_screen.py` / `report_filters.py` are unchanged and do not import it).

| Function | What it returns |
|---|---|
| `srs.to_weekly(daily, asof=None, drop_incomplete=False)` | W-FRI weekly OHLCV (open first, high max, low min, close last, volume sum), identical to `stock_screen.to_weekly` with defaults |
| `srs.trend(weekly, **params)` | `{'trend': 'up'/'down'/'none', 'swing_highs', 'swing_lows', 'used', 'reason', 'params'}` |
| `srs.info.info(ticker)` | inst own, short float, sector, industry, market cap, next earnings (FinViz, yfinance fallback) |

**Trend rule.** Swing high = weekly High above the 3 weeks before it and not below the 3 weeks after it
(fractal, `pivot_k=3`; swing low mirrored). Same-kind swings less than 12 weeks apart are merged, keeping
the more extreme (`min_sep_weeks=12`). **Up** means the last two swing highs are rising (the newest high may
be unconfirmed) and the last two swing lows before that high are rising. The current pullback after the
newest high is not judged (`pullback="ignore"`), but the trend is void if the latest weekly close is below
the last swing low (`break_close`). **Down** is the mirror. Anything else is **none**. Only the last 104
weeks are used. All parameters live in `srs.trend.TREND_DEFAULTS` and can be overridden from the CLI.

**Golden set.** `tests/golden_trend.yaml` holds Eyal's manual labels: 14 "no clear uptrend" calls and 116
technical stocks (PH, VOYA, DLTR plus his own TradingView drawings). Each label is evaluated as of its date
on frozen prices (`tests/data/golden_daily.csv.gz`). `pytest -s` prints the confusion matrix and every
miss. `python tools/tune_trend.py` runs the parameter grid, and `python tools/cv_trend.py` runs the
leave-one-out check.

### Install on a Mac

```bash
git clone https://github.com/azran4u/stock-retest-scanner.git
cd stock-retest-scanner
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
pytest -s                      # unit tests + golden-set accuracy report
```

### Commands

```bash
printf "PH\nNYSE:SWK\nNASDAQ:MU\n" > my.txt     # one per line; EXCHANGE:TICKER or comma lists work
srs fetch my.txt                       # 5y daily OHLCV -> ~/.srs_cache/<T>.csv (incremental)
srs fetch my.txt --years 5 --cache-dir ~/.srs_cache
srs weekly PH --last 10                # weekly candles (completed weeks; --include-incomplete for this week)
srs weekly PH --json --asof 2026-10-09
srs trend my.txt                       # table: trend, the 2 highs / 2 lows used, reason
srs trend PH,SWK --asof 2026-10-09 --json
srs trend my.txt --pivot-k 4 --min-sep-weeks 8   # override any TREND_DEFAULTS key
srs trend my.txt --fetch               # update the cache first
srs info PH,SWK                        # inst own / short float / sector / market cap / next earnings
```

`srs fetch` downloads with yfinance `auto_adjust=True`, the same as the daily scan. On a re-run it
re-downloads only the last 7 days. If those overlapping closes changed by more than 0.2% (a new dividend
or split re-adjusted the history), it re-downloads that ticker in full, so the cache stays consistently
adjusted.

## Python env (survives box restarts)

Box restarts drop `/workspace/.venv`. Every routine first runs `/workspace/ensure_env.sh`: it (re)creates `/workspace/srs_pyenv` (yfinance, pandas, numpy, requests, lxml, beautifulsoup4) if it's missing, and points `/workspace/.venv` at it, so `/workspace/.venv/bin/python` keeps working.

## Web app (iPhone, `/app/`)

**https://azran4u.github.io/stock-retest-scanner/app/** — installable PWA (Safari → Share → Add to Home Screen). Dark TradingView-style UI, Hebrew RTL.

- **List**: today's candidates (`app/data/index.json`) with search, filter chips (PASS / needs drawing / review / obsolete / hammer / position / my drawings / commands) and sort. The `hammer` badge requires $vol + history + no earnings ≤14d (hammer gate, see Last-week hammer). Each row has a **mini candlestick chart**: last 156 weekly OHLC candles (~3y, 124px tall, min/max labels) with a faint zone band and dashed entry line from the ticker's drawings; data from `app/data/spark.json` (export_data `spark_series`, OHLC quantized to 1 byte between lo/hi, base64), drawn lazily on canvas (IntersectionObserver). Persisted in localStorage. On desktop (≥720px) the cards sit in a grid (min 340px columns) and the mini chart keeps a 2.6:1 aspect ratio (redrawn on resize); the iPhone view is unchanged. Each card also shows **sector · industry** (FinViz quote page, yfinance fallback; `export_data.attach_sectors`, cache `/workspace/cache/sector_industry.json`, hits 120d / misses 7d; unknown = '—') and the **R:R + sizing** of the Long that counts (same live pick as PASS): shares = floor(maxRisk / (entry − SL)), risk$ = shares × (entry − SL), reward$ = shares × (TP − entry); maxRisk = account × max risk % from the dashboard sizing settings (localStorage `srs_sizing_v1`, default $5000 × 1% = $50); 0 shares = 'סטופ רחב מ-$50 למניה'. Recomputed live when a zone / Long is edited (`webapp/src/sizing.ts`, e2e `e2e_sizing.mjs`). **Sort** (control 'מיון:' next to the row count, persisted in localStorage): עדיפות (default) / **קרבה לאזור** / R:R / ציון פטיש / א-ב. 'קרבה לאזור' (Eyal 2026-10-24, instead of a near-zone PASS gate) = |current price − nearest edge of the live zone| / weekly ATR, 0 inside the zone, closest first, ties PASS first, no zone last; the live zone is the zone that counts in the app (else the exported TV zone), so an edit re-sorts immediately. Each card shows 'מרחק מהאזור: x.x ATR' (+ בתוך / מתחת לאזור). e2e `e2e_zone_sort.mjs`. **Chart indicators** (stock page, toggles under '+ אזור / + לונג', saved in localStorage; list mini charts follow): daily SMA 50/100/150/200 (weekly view = daily SMA at each week's last trading day; legend top-left) and **פיבונאצי** (last confirmed weekly ZigZag swing low, 3 x Wilder ATR(14), -> highest high after it; lines 0 / 0.382 / 0.5 / 0.618 / 1). Stock page section 'פיבונאצי' + list card line: price within 0.25 wATR of 0.382/0.5/0.618, zone coinciding with a level (±0.1 wATR). Informational, not a PASS gate. Manual anchors (no edit button): drag the Fib low / high end line directly (also from its price-axis label) or an end dot; on release it snaps to the nearest candle wick (low / high); 'אפס לאוטומטי'; label `fib_anchor` (e2e `e2e_fib_manual.mjs`). RULES.md §16; `srs_app/fib.py` = `webapp/src/indicators.ts` (`test_fib.mjs`, `tests/test_fib.py`, `e2e_indicators.mjs`).
- **Chart**: `lightweight-charts` v5, weekly ⇄ daily candles + volume. Prev / next buttons and horizontal swipe on the header / tool bar / panel; neighbours are prefetched.
- **Editing (touch)**: `+ אזור` then tap two price levels (first tap = start date); `+ לונג` then tap entry and stop (target starts at 2R). Select a drawing (its chart tag or its line in the panel) to get drag handles (top / bottom / entry / stop / target, and the start-date bar); when handles overlap (thin zone) the one nearest the pointer is grabbed. **The chart is the only editor (Eyal 2026-10-24):** the panel has no zone / Long inputs any more, only a read-only status line (live PASS/WAIT/FAIL + reason, R:R, shares / risk $ / reward $) and one compact line per drawing (levels, R:R, source / status badges) with its actions: 🗑 delete (own / TV), approve / reject / reopen (review), bot feedback behind "משוב". Live R:R. Delete own drawings, approve / reject bot drawings (`status=review`), technical yes/no + free note (`labels`), "send command to bot" (`commands`). Every edit is written to Supabase immediately; other open clients update via Realtime.
- **TradingView drawings** are imported into Supabase (`source='tv'`, `srs_app/import_tv.py`) and are normal editable drawings (small `TV` badge): drag handles, delete. **Delete is a soft delete** (`status='deleted'`, hidden in the app) for user and TV rows; bot rows keep approve / reject. `app/data/tv_drawings.json` is still generated but no longer loaded by the app.
- **Watchlist** (`watchlist` table): ☆/★ on list rows and the chart header; chip `★ מעקב`; type any symbol in the search box → "הוסף X למעקב" (also for tickers outside today's candidates). A ticker without candle JSON shows "no data yet"; the next daily run exports it (below).
- **לא מתאימה לשיטה** (Eyal 2026-10-24: one mark replacing 'לא מעניינת' + 'טכנית? כן/לא'). Stored as the existing label `not_interesting` (`value='yes'`, `until` = return date, `note` = `unfit` or `unfit: <reason>`; 'החזר עכשיו' writes `value='no'`; rows are never deleted). Duration picks 4 / 8 / 12 / 26 weeks (default 8, last pick remembered) or a custom date, optional reason; from 🚫 in the chart header (popover) or the panel section, which shows 'לא מתאימה לשיטה · חוזרת ב-dd/mm (עוד N ימים)' + 'החזר עכשיו'. Hidden from the list unless the `לא מתאימות לשיטה` chip is on (badge + 'חוזרת ב-dd/mm'); returns by itself after `until`. Nightly unchanged (`sync.SQL_NOT_INTERESTING_ACTIVE` → targets / needs-drawing / bot-drawing exclusion); every active mark ALSO counts as a "doesn't fit / not technical" verdict for the technical-feedback learning: `sync.unfit_marks(rows)` → {ticker: until, reason, merged}. Old `technical` labels stay in the table as history (none were active "no" at the merge; the only not_interesting row, MU 2026-10-20, was already `no` → nothing to migrate).
- **Auth**: Supabase email OTP (magic link **or** the 6-digit code typed in the app — needed for the home-screen PWA, which on iOS does not share Safari's storage). Session persists in localStorage. RLS: only `azran4u@gmail.com`.
- Demo / test mode: `?demo=1` (in-memory backend, nothing is written anywhere) — used by `webapp/e2e.mjs`.

### Layout

| Path | Purpose |
|---|---|
| `webapp/` | Source (Vite + TypeScript). `npm install && npm run build` → writes `app/index.html`, `app/assets/*`, manifest, icons, `sw.js` (base `/stock-retest-scanner/app/`). `node e2e.mjs` = headless iPhone smoke test against `npx vite preview` |
| `app/` | Built site served by Pages (committed; legacy Pages build from `main` /) |
| `app/data/` | Generated data: `index.json`, `tv_drawings.json`, `candles/<T>.json` (daily OHLCV 5y: `{"t":T,"d":[[date,o,h,l,c,v],…]}`) |
| `srs_app/export_data.py` | Generates `app/data/` from `historical-reports/latest.csv`, `tv_drawings.json` and the scanner's history cache `/workspace/hist_cache.pkl` (same yfinance data as the screen). Candidates = PASS ∪ needs drawing ∪ bot review ∪ obsolete ∪ last-week hammer ∪ any TV drawing ∪ open position |
| `srs_app/sync.py` | SQL + parsers for the bot to read app edits (below), app state file (watchlist / not interesting) |
| `srs_app/import_tv.py` | TradingView store → idempotent SQL inserts into `drawings` (`source='tv'`, `tv_key`, `ON CONFLICT (tv_key) DO NOTHING`) |
| `srs_app/app_drawings.py` | App drawings (SQL rows) → `/workspace/stock-screener/app_drawings.json` in the `tv_drawings.json` shape; `export_daily_report.py` prefers it |

### Daily publish

`export_daily_report.py` calls `srs_app.export_data.export()` at the end (guarded; never blocks the report), so the nightly run refreshes `app/data/`. Commit it with the report: `git add app/data historical-reports … && git pull --rebase && git push`. After a nightly TradingView read / `tv_drawings.py merge`, refresh manually: `cd /workspace/publish-stock-retest-scanner && /workspace/.venv/bin/python -m srs_app.export_data` and commit `app/data`. Rebuild the UI only when `webapp/src` changes (`cd webapp && npm run build`, commit `app/`).

### Reading the app's tables (bot, via the Supabase connector)

No service key on the box: run SQL with the Supabase connector (`execute_sql`, project `wkkdblnykgolqijzagva`), then parse with `srs_app.sync` (`levels_by_ticker`, `labels_by_ticker`, `pending_commands`).

```sql
-- current drawings (rejected / obsolete excluded; review = bot proposals not yet approved)
select id, ticker, kind, zone_top, zone_bottom, entry, stop, target, t_start, t_end, source, status, note, updated_at
from public.drawings where status in ('active','approved','review') order by ticker, kind, updated_at desc;

-- one ticker
select * from public.drawings where ticker = 'CSCO' order by updated_at desc;

-- latest label per ticker (technical = yes/no, note = free text)
select distinct on (ticker, label) ticker, label, value, note, asof, created_at
from public.labels order by ticker, label, asof desc, created_at desc;

-- commands Eyal sent from the app, oldest first
select id, ticker, text, created_at from public.commands where status = 'pending' order by created_at;

-- mark one handled (reply is shown under the command in the app)
update public.commands set status = 'done', reply = '…', done_at = now() where id = 42;

-- bot drawing (source='bot', status='active' = approved by default since 2026-10-23); use srs_app.bot_drawings --emit-sql
insert into public.drawings (ticker, kind, zone_top, zone_bottom, t_start, source, status, note, meta)
values ('OKE', 'zone', 70.5, 68.0, '2026-05-04', 'bot', 'active', 'BOT v3d', '{"rule_version":"v3d-2026-10-23","why":{}}'::jsonb);
```

### Bot drawings + feedback (policy 2026-10-23)

**Bot drawings approved by default + feedback loop (policy 2026-10-23, Eyal: "everything is approved unless I say otherwise; I want you to be independent").**
- **Trend calibration page (`#/calibrate`, 'כיול מגמה', 2026-10-26):** ~60 tickers from `app/data/calibration.json` (`[{ticker, group: clear_up|clear_not|unsure, bot_view, rule_result, reason_he, sector}]`) in three sections ('ברור שבמגמה עולה' / 'ברור שלא' / 'מתלבט') with a 3-year weekly chart + weekly EMA30 (`spark.json` `ema30`, exported for the calibration tickers by `export_data.export` — their candles / spark stay in every export), the bot's view + reason, and his mark 'מגמה עולה' / 'לא' / 'לא בטוח' + note → `public.labels` label `uptrend_mark` (value up / not / unsure, asof today). Calibration only: never changes `f_technical`, which is recomputed every night (a `user_overrides.json` technical verdict holds 7 days or until its `until`).
- **Approved by default:** bot drawings (`source='bot'`, `status='active'`) count toward `f_rr` / PASS exactly like his own drawings (`srs_app/app_drawings._counts`: any `active` / `approved` row counts; report `tv_source = bot-approved`, `tv_bot_status = bot drawing (auto-approved)`; app card badge `בוט`, status `פעיל (מאושר אוטומטית)`). The 20 tickers' TV-imported bot rows that were in `review` (ALSN, CNO, COP, DXCM, EHC, ELV, ESS, EW, MA, MSI, OKE, OXY, PKG, PM, PR, RS, TRV, UNM, VLTO, VRSN) were converted to `source='bot', status='active'` (meta `rule_version = tv-bot-2026-10-04`). Supersedes "bot drawings stay at review until approved".
- **Drawing:** `python -m srs_app.bot_drawings` (nightly step; `--print-read-sql` → run the 3 reads with `execute_sql`, save the JSON → `--drawings-json D --labels-json L --feedback-json F --emit-sql` → run the printed SQL). Rules v5 (`RULE_VERSION = v5-2026-10-26`, Eyal 2026-10-26; `ZONE_SCORING = "v5"`): **the zone is (a) a broken resistance retested from above or (b) a return to a previous support, PLACED to touch as many points as possible** — points = weekly closes, weekly highs and weekly lows (each counted on its own; one-day spike wicks already cleaned) of the last `TOUCH_LOOKBACK_W` = 52 weeks inside zone ± `TOUCH_TOL_ATR` = 0.25 weekly ATR (`points_in`). Every candidate level (the v4 set: clarity ≥ 2, unbroken / reclaimed, below the price, from above, ≤ `FAR_CAP_ATR` = 3 weekly ATR below the close) keeps its width and slides by up to `V5_SHIFT_ATR` = 0.15 ATR (0.05 steps; a shift must win ≥ `V5_MIN_GAIN` = 8 points and may not break the level — no low under its new SL since the pivot / reclaim — lift it above the price, make it 'from below' or far) (`place_v5`). Pick = max(points − `V5_PROX_W` 80 × ATR from the close down to the zone top − `V5_RECENCY_W` 24 × pivot age in years), ties → nearer → newer → daily touches → clarity. Weights from a sweep against his 126 live user / TV zones (`python -m srs_app.zone_eval --drawings-json D`, as-of = TV read date or creation date, match = IoU ≥ 0.3): v4 43/126 (34.1%, mean IoU 0.252) → v5 48/126 (38.1%, 0.266); a points-first pick (PROX 1–3) or larger shifts (0.25 / 0.5 ATR) matched far less (9–34 of 126) — his zones sit near the price, so nearness weighs heavily. `meta.why` adds `rule: v5`, `points`, `shift_atr`. The Long is unchanged (entry = zone top − 0.13 weekly ATR, SL = `infer_v3d.sl_d` 'fit', TP = 26-week max body top − 0.09 ATR, 20 weekly bars). Previous: v4 (2026-10-23) = (**zone scoring by touch count** (his principle 2026-10-23: the PRIMARY criterion is how many weekly closes / wicks reached the zone; a bar touches when its close, low or high is inside zone ± `TOUCH_TOL_ATR` = 0.25 weekly ATR, consecutive touching bars = one touch, counted over the last `TOUCH_LOOKBACK_W` = 52 weeks); pick = max(weekly touches − `PROX_W` 3 × ATR from the close down to the zone top − `RECENCY_W` 6 × pivot age in years — the RECENT support/resistance wins among viable levels), ties → daily touches → newer pivot → clarity; clarity is only a sanity check (≥ 2, was a hard ≥ 3 skip); `meta.why` adds `touches_w`, `touches_d`, `pivot_age_w`, `weeks_since_touch`, `alt_levels` (top 4 candidates with their touches); his old drawings are a soft reference, not a regression veto. Built on v3e: : v3d + reclaimed levels count again (≥ 2 weekly closes back above, not if the price fell back under them: bottom ≤ close + 0.3 ATR) + pullback measured from the latest swing high, approved after the QCOM feedback; + the last higher low before the latest high counts with clarity 2 (TWST; his old drawings are a soft reference, not a veto); `c` = spike-wick cleaning (HWC), see RULES.md; params frozen from the 54-drawing fit; `b` = far cap: no zone more than `FAR_CAP_ATR` = 3 weekly ATR below the close — it would be obsolete 'far' on arrival; his own zones were ≤ 1.8 ATR below price — such tickers get no bot drawing (reason "price ran away")). Candidates: `f_dollar_vol AND f_history AND f_no_earnings_14d AND f_technical`, no live user/tv row, not `not_interesting`, not `tv_source = user-lines`, (since 2026-10-26: feedback / rejection no longer excludes — a rejected bot drawing is redrawn under the current rules unless the new levels equal the rejected ones, `drop_same_as_rejected`), no live bot row (a live bot row that is broken — any low since it was drawn < SL — or target hit — latest close ≥ TP — or far — close > zone top + 3 weekly ATR — → `obsolete` (meta.obsolete = {at, why}) + redrawn; live bot rows of tickers outside the candidate list or next to his own drawing are only retired). Long Position time-anchored (`t_start` = week after the last candle, `t_end` = +20 weekly bars). Every row stores `meta = {rule_version, why: {rule, branch, pivot_date, breakout_date, clarity, wick_confirmations, sl_src, sl_wick_low, atr, atr_w, risk_atr_w, pullback_low, recent_high, fib382, n_valid_levels, price_below_zone, dist_price_to_zone_top_atr, entry_rule, tp_rule, data_date}}`.
- **Feedback (app, on bot cards):** `אזור לא נכון` (zone row), `פוזיציה לא נכונה` (long row), optional `מאושר` (status `approved`), plus an optional note. Negative feedback sets the rows to `rejected` immediately (never counts; redrawn on the next run under the current rules unless the levels come out the same) (the 'structure' option was removed on 2026-10-26; the only exclusion from bot drawing is his 'unfit for the method' mark, for its period). Each submission inserts `public.commands` (`kind='feedback'`, `text='[feedback] <category>: <note or Hebrew label>'`, `payload={ticker, drawing_ids, category, category_he, note, before{zone|long: levels}, after{…}|null, rule_version, why}`) so the INSERT webhook fires, and a `public.drawing_feedback` row (owner-only RLS) linked by `command_id`. The bot's reply on that command shows under the drawing.
- **His edits win:** the first drag / edit of a bot row makes it his (`source='user'`), keeping the bot's levels in `meta.bot_before` (+ `edited_at`); feedback on it sends before/after.
- **Regression:** `tests/test_bot_drawings.py` reproduces (under the v4 'touches' pick, pinned by the `v4` fixture) the 55 stored v3d drawings (`tests/golden/bot_drawings_golden.json`) from the committed price fixture (`tests/golden/hist_golden.csv.gz`, data ≤ 2026-10-02) with the vendored rule code (`srs_app/v3d/`, copied from `/workspace/drawing-learn`; `SRS_DRAWING_LEARN` overrides the dir) — it never skips — and the candidate rules — plus v5 cases (QCOM / TWST overlap his zones, `points_in`, `place_v5`) — run it before shipping any rule change (bump `RULE_VERSION`).

### Nightly routine additions (TradingView retirement)

TradingView is being retired: the app becomes the only drawing source. `drawings.tv_key` = `TICKER:kind:levels` (zone `top-bottom`, long `entry/stop/target`, 2 dp); `source` ∈ user | bot | tv; `status` adds `deleted` (soft delete).

1. **After the (last) nightly TV read** — import new TV drawings only (a row Eyal edited or deleted is never overwritten or resurrected):
   ```bash
   cd /workspace/publish-stock-retest-scanner && /workspace/.venv/bin/python -m srs_app.import_tv --out /workspace/tv_import_sql
   ```
   then run each `/workspace/tv_import_sql/batch_*.sql` through the Supabase connector `execute_sql` (project `wkkdblnykgolqijzagva`; pass `"query": "$file:/workspace/tv_import_sql/batch_001.sql"` etc.). Each returns `{"inserted": N}`. TV drawings still marked bot ("BOT - review needed") come in as `status='review'`.
2. **App state for the offline scripts** (watchlist → candles; not interesting → target exclusion; manual Fib anchors → `fib_*` export): run `sync.SQL_WATCHLIST`, `sync.SQL_NOT_INTERESTING_ACTIVE` and `sync.SQL_FIB_ANCHORS` with `execute_sql` (`write_to_file: true`), then
   ```bash
   cd /workspace/publish-stock-retest-scanner && /workspace/.venv/bin/python -m srs_app.sync --watch-json <watchlist file> --ni-json <not-interesting file> --fib-json <fib anchors file>
   ```
   → `/workspace/stock-screener/app_state.json`.
3. **App drawings = source of truth per ticker** (before `export_daily_report.py`): run `app_drawings.SQL_APP_DRAWINGS` with `execute_sql` and `write_to_file: true`, then
   ```bash
   cd /workspace/publish-stock-retest-scanner && /workspace/.venv/bin/python -m srs_app.app_drawings --from-json <that file>
   ```
   → `/workspace/stock-screener/app_drawings.json` (accepts the connector's raw output). When it exists `export_daily_report.py` uses it instead of `tv_drawings.json` (`--tv-store` forces the old store), so PASS / R:R / needs drawing / review come from the app. Newest row per ticker+kind; user, tv and approved bot rows count (owner user); bot proposals in review stay "bot drawing (review needed)"; zone without long = partial "Rectangle only, no Long Position" (long without zone = "LP only, no Rectangle"); a ticker whose drawings were all deleted becomes "no drawing".
4. The daily export then writes `app/data` (incl. watchlist tickers: candles downloaded from yfinance when not in the scanner cache). Commit `app/data` with the report.

```sql
-- converter input (app_drawings.SQL_APP_DRAWINGS)
select id, ticker, kind, zone_top, zone_bottom, entry, stop, target, t_start, source, status, tv_key, note, created_at, updated_at
from public.drawings
where kind in ('zone', 'long') and status in ('active', 'approved', 'review')
order by ticker, kind, updated_at desc;

-- source of truth only (user + tv + approved bot), newest per ticker+kind (sync.SQL_SOURCE_OF_TRUTH)
select distinct on (ticker, kind) id, ticker, kind, zone_top, zone_bottom, entry, stop, target, t_start, source, status, tv_key, updated_at
from public.drawings
where kind in ('zone', 'long') and (status = 'active' and source in ('user', 'tv') or status = 'approved')
order by ticker, kind, updated_at desc;

-- watchlist (sync.SQL_WATCHLIST)
select ticker, note, added_at from public.watchlist order by added_at;

-- active "not interesting" tickers (sync.SQL_NOT_INTERESTING_ACTIVE_ONLY)
select ticker, until from (
  select distinct on (ticker) ticker, value, until
  from public.labels where label = 'not_interesting'
  order by ticker, asof desc, created_at desc
) x where value = 'yes' and (until is null or until >= current_date) order by ticker;
```

**Not interesting = excluded, data still computed:** `export_daily_report.py` drops active not-interesting tickers (from `app_state.json`, checked against the report date) from `grok_needs_drawing_target` and `grok_review_target`; all report columns are still computed for them. Bot-drawing generation and review prompts must skip them too (`sync.not_interesting_from_state()`).
