# Stock retest screener — rules

Last updated: 2026-09-29 (standalone ANDed report filters; earnings cache-until-past for every FinViz ticker)
Owner: Eyal  
Watchlist: TradingView `Grok`  
Tools: FinViz screener (filters) → code scan (yfinance) → TradingView drawings (no live orders)

---

## 0. Roles (split bots)

| Bot | Job |
|-----|-----|
| **Grok Bot** | FinViz + code screen, daily report, TradingView drawings + **`Grok` watchlist sync** |

Single driver: **Grok Bot** owns TradingView on this desktop (drawings + watchlist). Do not spin up a second TV driver teammate.

---

## 1. FinViz base filter (user-maintained)

Start from the FinViz technical screener the user keeps updated. Recent snapshot used:

- Country: USA  
- Average volume: Over 100K  
- Institutional ownership: Over 80%  
- Price: Over $10  
- Price **above** SMA200  
- Price **below** SMA50  
- View / sort: as set by user (e.g. technical view, order by company)

Do **not** change FinViz filters unless the user asks. If the user tightens the screener, use the new result set.

Screener URL pattern (example):  
`https://finviz.com/screener?v=171&f=geo_usa,sh_avgvol_o100,sh_instown_o80,sh_price_o10,ta_sma200_pa,ta_sma50_pb&ft=3&o=company`

---

## 2. Hard filters (after FinViz)

The screen (`stock_screen.py`) still applies these cheap-first for its `reason` text, but the **report** evaluates every rule independently for every row as standalone `f_*` columns (§12 “Report filters — standalone, ANDed”); `status=PASS` = all core filters. Short float N/A and unknown earnings now count as **not** passing.

### 2.1 Liquidity
- Dollar volume = **30-day average volume × last close** ≥ **$50,000,000** USD  
- (Code constant: `AVG_VOL_DAYS = 30`; not 20-day.)  
- If 30d dollar volume is under $50M → **FAIL**

### 2.2 History
- At least **~3 years** of trading / price history  
- Short IPO / short chart history  → **FAIL**

### 2.3 Short float
- Short float **&lt; 5%**  
- Checked on FinViz quote (not available as a reliable FinViz screener filter)  
- ≥ 5% → **FAIL**

### 2.4 Earnings blackout
- Runs for **every** FinViz ticker (not only survivors of other rules) — `stock_screen.write_universe_data` → `get_next_earnings`.
- Source: TradingView symbol page HTML (`earnings_release_next_date_fq`, retry/backoff on 429/503) primary; Yahoo/yfinance fallback.
- **Earnings cache `cache/earn_{TICKER}.json` stores the absolute next earnings DATE** (YYYY-MM-DD, never days). It is **reused until that date has passed**; a past or missing date is refetched. A “no date found” result is cached as a miss and retried after `EARN_MISS_TTL_HOURS` (20h); TradingView rate-limit failures are not cached.
- `days_to_earnings` in the CSV is as of the report date (drives `status`); the Pages dashboard **recomputes** days-left, `earnings_blackout` and the **no earnings ≤14d** checkbox live from `earnings_date` (Asia/Jerusalem); a date already passed counts as unknown.
- If known and `0 <= days_to_earnings < 14`, set `earnings_blackout=true` and **fail/skip — it must **not** get `status=PASS` (no drawing or `Grok` watchlist entry).
- Unknown earnings data remains blank/NaN and must be called out with `earnings_known=false`; do not treat unknown as confirmed earnings-safe.  

### 2.5 Known examples (not hard-skips)
- No ticker is hard-skipped in code. Short-history / thin names fail via §2.1–2.2 only.  
- **AMP** — teaching example; typically fails R:R (~1.09–1.13) under geometry rules (still analyzed)  

---

## 3. Chart pattern — “close to retest”

Analysis of support / resistance is on the **weekly** timeframe.

### 3.1 Setup
1. Clear **prior resistance** that was **broken to the upside**  
2. Price **pulls back down** toward that broken resistance to test it as **support**  
3. Pullback / down move on **relatively low volume** (below average / quieter than the breakout)  
4. **Reversal candle** at / near that support (e.g. hammer, bullish engulfing, long lower wick rejection, strong bullish close after the pullback)

### 3.2 Support / resistance zone definition

- **Peak candle** is chosen by **highest body top** locally: swing highs are local maxima of `max(Open, Close)`, **not** of wick `High`.
- Zone = that peak candle’s body top → wick high:
    - **Zone top (`zone_hi`)** ≈ peak candle **wick high** (`High`)
    - **Zone bottom (`zone_lo`)** ≈ peak candle **body top** (`max(Open, Close)`) — rectangle bottom should **touch the candle’s body top**
- Example (AMP, teaching example): zone **537.5 – 544.2**
- Example (R): use the week with the higher body (e.g. week after a tall-wick spike), not the wick-high week alone.

Skip if resistance isn’t clear, historical pullback to the zone didn’t happen, pullback volume isn’t relatively low, or geometry/R:R fails. Current price distance from entry is **not** a skip reason.

Prefer common stocks over ETFs / CEFs / leveraged products unless the user says otherwise.


---

## 4. Trade geometry (Long Position — drawing only)

> **Source of truth (2026-09-29): the user's TradingView drawings.** Zone, entry, SL, TP and R:R are **read** from the user's own drawings on the weekly chart — the **Rectangle** = zone (`tv_zone_top` / `tv_zone_bottom`) and the **Long Position** tool = entry / stop / target and TradingView's own **R:R** (`tv_entry`, `tv_sl`, `tv_tp`, `tv_rr`). A browser agent reads them daily, **read-only**. **The drawings must never be modified** — no moving, resizing, re-drawing, deleting or restyling of any rectangle / Long Position / other drawing; the agent only opens the chart and reads values. The scanner-computed geometry below (§4.1–4.4) is legacy: it is still computed as internal info (`f_rr_computed`, **not** part of `status`) and is **never displayed** on the dashboard. The R:R ≥ 2 rule (§4.4) now applies to the **TradingView** R:R. See §12 “TradingView drawings”.

**Never place a live / broker order.** Only draw TradingView’s **Long Position** panel.

### 4.1 Entry
- **Middle of the rectangle** = `(zone_top + zone_bottom) / 2`

### 4.2 Stop loss
1. Consider weekly candles whose **body top** (`max(Open, Close)`) **or wick top** (`High`) is **inside** the rectangle  
2. Among those, take the candle with the **deepest bottom wick** (lowest `Low`) — if several qualify, use the longer / deeper one  
3. Place stop **below** that wick  
4. ATR band on stop **distance from entry** (weekly ATR(14) unless user changes TF):  
   - **Minimum:** **0.5 × ATR** (if wick stop is tighter, **widen** SL to `entry − 0.5×ATR`)  
   - **Maximum:** **1.0 × ATR** (if wick stop is wider, **cap** SL at `entry − ATR`)  

### 4.3 Take profit
- At the **latest swing high’s candle body top** only  
- Use `max(Open, Close)` of that high candle — **exclude wicks**

### 4.4 Risk / reward
- `R:R = (TP − entry) / (entry − SL)`  
- Require **R:R ≥ 2** (at least **1:2**)  
- If R:R &lt; 2 → **FAIL / skip** (do not add to watchlist)

### 4.5 Distance to entry (informational)
- `atrs_from_entry = (current_price − entry) / ATR` (signed; **+** = price above entry)
- **Not** a pass/fail filter. R:R uses entry / SL / TP only; a PASS may still be far from entry.
- Dashboard default sort: R:R desc, then `atrs_from_entry` asc (closer first). Shift-click for secondary sort.

---

## 5. TradingView drawing rules

When a ticker **fully passes**:

1. **Confirm the US listing before anything else** (exchange check):  
   - FinViz screen is **USA only** — the chart and `Grok` add must be the **US** equity (NYSE / NASDAQ / etc.), not a same-ticker foreign listing.  
   - In TradingView symbol search, **pick the exchange explicitly** — do not accept the first hit for a bare ticker.  
   - Verify company name + price level match the pass-queue levels (e.g. zone / entry) before drawing.  
   - **Known collision:** `ASB` = **NYSE Associated Banc-Corp** (~$29, zone ~28.63–28.77). Never use **ASX Austal Limited** (~AUD 4). If the wrong listing is on `Grok` or the chart, remove/switch it before continuing.  
2. Open the **confirmed US** symbol on **weekly (1W)**  
3. Draw the **resistance / support rectangle**:  
   - Vertical: `zone_bottom` → `zone_top` (body top → wick high of peak candle)  
   - Horizontal **left**: include the **previous high that was broken**  
   - Horizontal **right**: stretch to the **current date** / latest bar  
4. Place the **Long Position** panel **to the right of the rectangle** (after the zone on the right), with entry / SL / TP from §4  
5. **Add** the **confirmed US** symbol to the watchlist named exactly **`Grok`** (same exchange check as step 1)  
   - This means the **watchlist panel** entry — **not** an Object Tree / drawing group also named “Grok”.  
   - After Add Symbol, **scroll the `Grok` watchlist and confirm the ticker is visible** before marking the ticker done.  
6. Then **continue** to the next passing stock  

Do **not** add stocks that fail any filter. Do **not** add a foreign same-ticker twin.

---

## 6. Process / workflow

1. User maintains FinViz filters  
2. **Bulk** pull screener tickers + OHLC / short% / earnings in **code** (fast path) — avoid per-ticker browser clicking for scanning  
3. Log **every** analyzed ticker with pass/fail **reason** (debug)  
4. For each full **PASS**: TradingView drawings + `Grok` watchlist, then next  
5. Use browser chart work mainly for **drawing** passers, not for scanning hundreds of names  

Artifacts (typical paths on the bot computer):
- `/workspace/stock_screen_results.txt` — full debug list  
- `/workspace/stock_screen_results.csv` — all tickers debug
- `historical-reports/YYYY-MM-DD.csv` — published full-universe daily report (repo)  
- `/workspace/stock_screen_verify.csv` — verification table: all PASSes (+ R:R fails with geometry), **sorted by R:R descending**  
- `/workspace/stock_screen_verify.html` — same table as static HTML for easy review  
- Verify columns: ticker, status, current_price, entry, sl, tp, rr, atrs_from_entry, zone_lo, zone_hi, atr, short_float_pct, inst_own_pct, dollar_vol_30d, avg_vol_30d, weekly_bars, earnings_date, days_to_earnings, earnings_known, earnings_blackout, tradingview_url, reason  
- `tradingview_url` best-effort US exchange as portable https (`https://www.tradingview.com/chart/?symbol=NASDAQ:…`); `MOG-A` → `MOG.A`; dashboard ticker opens app via `tradingview://` (best-effort; TV often ignores symbol if app already open); web link always has the chart  
- `days_to_earnings` is populated directly in the verification outputs; unknown values are blank/NaN and flagged. The 14-day blackout rule still controls the PASS/draw queue.  
- `/workspace/pass_queue.json` — current earnings-safe pass queue with levels  
- `/workspace/earnings_filter_log.txt`  
- `/workspace/sl_atr_floor_log.txt`  
- This file: `/workspace/stock-screener/RULES.md`

---

## 7. Checklist (quick)

- [ ] In FinViz base set  
- [ ] $vol ≥ $50M (**30d avg vol × last close**)  
- [ ] History ≥ ~3 years  
- [ ] Short float &lt; 5%  
- [ ] Next earnings **not** within 14 days  
- [ ] Weekly retest (broken resistance → low-vol pullback → reversal at zone)  
- [ ] Peak = local max of weekly body top (not wick); zone = that candle body-top → wick-high; rectangle to prior high and to today  
- [ ] Entry = mid-zone  
- [ ] SL under deepest wick among candles with body top **or** wick top inside the zone, then clamp to **[0.5×ATR, 1×ATR]**  
- [ ] TP = latest high **body** top  
- [ ] R:R ≥ 2  
- [ ] Draw Long Position (no order) to the **right** of rectangle  
- [ ] **US exchange confirmed** in TV search (not a foreign same-ticker); price matches pass-queue levels  
- [ ] Add **that** US listing to watchlist `Grok` and **verify it appears in the watchlist panel** (not only a drawing group named Grok)  

---

## 8. Notes / limitations

- Code heuristics approximate discretionary chart reading; false positives/negatives expected — user reviews drawings  
- ATR timeframe: weekly when geometry is weekly  
- Short float / earnings sourced from FinViz / Yahoo-style data feeds; missing data should be called out in the debug log

---

## 9. Cadence

- After finishing a full pass over relevant FinViz names, **re-run once per day on US trading days only** (weekdays; skip weekends / US market holidays when detectable).
- Schedule target: **23:00 Asia/Jerusalem** weekdays (after the US regular session for that day).
- **Do not scan the same ticker twice on the same calendar day** — track in `/workspace/stock-screener/scanned_today.json`.
- Routine name: **Daily retest stock screen**.

---

## 10. TradingView session isolation (root-cause fix)

**Problem we hit:** the daily routine and a chart-drawing run both drove the **same** Chrome on **this** bot’s desktop at once → Add Symbol spam, wrong tickers, watchlist side effects (e.g. `grok_upload`), and symbols added to `Grok` before drawings finished.

**How the computer works (important):**
- This bot has **one** desktop and **one** interactive browser session for GUI automation.
- Chart-drawing subagents share that same desktop/screen — they are **not** separate bots with separate Chromes.
- Opening extra **tabs** does **not** isolate two automations: both still click/type in the same browser and will fight.
- A **different teammate bot** would get its **own** desktop/browser — that *is* real isolation, but only if we deliberately split roles across agents.

**Rules going forward:**
1. **Only one TradingView driver at a time** for this bot — never run the daily routine’s TV drawing path in parallel with a chart-drawer task.
2. While a drawing backlog exists, the daily routine may **code-scan only** (FinViz/yfinance) and queue PASSes; it must **not** open TradingView until drawings are idle.
3. Watchlist **membership** for `Grok` is synced from the daily report PASS set (add/remove) after each report. For drawing a ticker: **exchange check → draw zone → draw Long Position**.
4. Target watchlist remains **`Grok`**. Do not create other lists. Leave `grok_upload` alone unless the user asks to change it. Always select the **US exchange** in symbol search (see §5) — bare tickers can resolve to foreign listings (e.g. ASB ASX vs NYSE).
5. **Single bot:** Grok Bot runs the code screen, publishes the report, syncs **`Grok`**, and draws setups. Do not use a separate Grok Bot teammate.

---

## 11. Watchlists

| List | Purpose |
|------|---------|
| **Grok** | Tickers that **passed every filter** in the latest report (`status=PASS`). Synced after each report: add PASSes, remove anything that did not pass. |
| **Grok queue** | Optional staging list; prefer syncing **`Grok`** from the report. Leave alone unless needed. |
| **grok_upload** | Leave alone unless user asks |

After the daily report, sync **`Grok`** to the full PASS set (see §12). Drawings for new PASSes can follow on this same bot.

---

## 12. Reports (historical CSVs + GitHub Pages)

### Goal
Every daily screen produces a **full-universe** CSV of **all** FinViz-returned tickers (PASS and FAIL), not only PASSes. These feed the public dashboard on GitHub Pages.

### Output paths (repo `azran4u/stock-retest-scanner`)
- `historical-reports/YYYY-MM-DD.csv` — dated full report
- `historical-reports/latest.csv` — copy of the newest dated file
- `historical-reports/*.csv` — only copy of report CSVs (Pages source = `/`)
- `reports.json` — manifest for the report-date picker: `[{date, file, path}, ...]`
- `index.html` — dark dashboard (Chart.js CDN); fetches CSVs from `historical-reports/`
- TV links: CSV stores https; dashboard ticker opens app via `tradingview://` (best-effort; TV often ignores symbol if app already open); web link always has the chart

### Columns
Same spirit as the verify table, for every ticker:

`ticker, status, failed_filters, f_dollar_vol, f_short_float, f_no_earnings_14d, f_history, f_rr, f_rr_computed, f_smooth_streak, f_weekly_reversal, f_daily_reversal, f_near_zone, needs_drawing, current_price, dollar_vol_30d, avg_vol_30d, short_float_pct, inst_own_pct, earnings_date, days_to_earnings, weekly_bars, zone_lo, zone_hi, entry, sl, tp, rr, sl_atr_mult, atr, atrs_from_entry, tv_found, tv_zone_top, tv_zone_bottom, tv_entry, tv_sl, tv_tp, tv_rr, tv_read_date, tv_screenshot, tv_price, tv_weekly_atr, tv_zone_dist, tv_zone_dist_atr, smooth_streak_weeks, weekly_reversal_kind, weekly_reversal_date, daily_reversal_kind, daily_reversal_date, smooth_pullback, earnings_known, earnings_blackout, filter_notes, tradingview_url, finviz_url, reason` (see “Report filters — standalone, ANDed”). Reports before 2026-09-28 use the older schema.

- Prefer verify-enrichment (earnings / TV URL / pct fields) where tickers overlap.
- Remaining names get pct conversion from `short_float` / `inst_own`, best-effort `tradingview_url`, and blank/false earnings fields when unknown.

### Helper
`export_daily_report.py` (also under `/workspace/stock-screener/` on the bot box):

```bash
python export_daily_report.py \
  --results /workspace/stock_screen_results.csv \
  --verify /workspace/stock_screen_verify.csv \
  --date YYYY-MM-DD \
  --out-dir ./historical-reports \
  --docs-dir ./docs \
  [--handoff /workspace/stock-screener/handoff_YYYY-MM-DD.json]
```

Call this at the end of the daily routine after `stock_screen.py` finishes, then commit + push so Pages updates. The export computes **all** standalone filter columns for every row automatically (`report_filters.py`), sets `status` from the core filters, and writes `/workspace/stock-screener/grok_sync_target.{json,txt}` (PASS set). Any `report_filters` CONFIG key can be overridden as a flag, e.g. `--min-smooth-streak-weeks 6`.


### After each report — sync `Grok` watchlist
1. From the new report CSV, take every ticker with **`status=PASS`** = `f_dollar_vol AND f_short_float AND f_no_earnings_14d AND f_history AND f_rr`, where `f_rr` = TradingView drawing found AND TV R:R ≥ 2 (see “TradingView drawings”; a missing drawing blocks PASS) (earnings blackout / unknown earnings, R:R, short float N/A all block PASS). `export_daily_report.py` writes this set to `/workspace/stock-screener/grok_sync_target.{json,txt}`.
2. Build the target set as `EXCHANGE:TICKER` using FinViz-resolved US exchanges (same as `tradingview_url`).
3. **Grok Bot** syncs TradingView watchlist **`Grok`** to that exact set on **this** desktop:
   - **Add** any PASS missing from `Grok`
   - **Remove** any symbol currently on `Grok` that is **not** a PASS in the report
4. Do this **after** the report is published. Membership sync does not wait on drawings; drawings for new PASSes can run after.
5. Leave `grok_upload` alone. No separate Grok Bot teammate.


### Dashboard URL
https://azran4u.github.io/stock-retest-scanner/


### TradingView drawings — zone / entry / SL / TP / R:R (2026-09-29)

- **Source of truth:** the user's TradingView drawings, **read-only**. Rectangle = zone; Long Position tool = entry, stop, target and TradingView's R:R. **Never modify the drawings** (no move / resize / redraw / delete / restyle; never place orders). The scanner's own computed zone/entry/SL/TP/R:R are inaccurate and are **never shown** on the dashboard.
- **Daily read targets:** report rows passing `f_dollar_vol AND f_short_float AND f_no_earnings_14d AND f_history` (**no smooth-streak requirement** since 2026-10-01, so the nightly read covers every stock that could PASS or needs a drawing), with `f_no_earnings_14d` evaluated **live vs today** from the cached earnings date (same as the dashboard). `python tv_drawings.py targets` → `/workspace/tv_read_targets.txt` (`EXCHANGE:TICKER` per line, exchange from `tradingview_url`) + `/workspace/tv_read_targets.json`.
- **Store:** `/workspace/stock-screener/tv_drawings.json`, keyed by ticker: `found, zone_top, zone_bottom, entry, sl, tp, rr, read_at (ISO), read_date` (+ `symbol`).
- **Record a read:** `python tv_drawings.py upsert NYSE:ST --zone-top 41.96 --zone-bottom 41.31 --entry 42.11 --sl 38.46 --tp 51.55 --rr 2.59` · no drawing on the chart: `python tv_drawings.py upsert NYSE:XYZ --not-found`.
- **Merge:** `python tv_drawings.py merge` writes `tv_found, tv_zone_top, tv_zone_bottom, tv_entry, tv_sl, tv_tp, tv_rr, tv_read_date` into `latest.csv` + its dated twin from the **latest stored reading per ticker** (any ticker with a reading, not only today's targets), sets `f_rr`, **recomputes `status` / `failed_filters` / `reason`** and **regenerates `/workspace/stock-screener/grok_sync_target.{json,txt}`** (`--no-grok-target` to skip). The nightly path does the same without a separate step: `stock_screen.py` gates its screen status on the stored reading, and `report_filters.apply_filters_to_report` (used by `export_daily_report.py`) reads `tv_drawings.json` directly. `tv_found` = `yes` / `no` / empty (never read). After recording new reads, run `merge` so status and the Grok target pick them up.
- **`f_rr` = TradingView drawing found AND `tv_rr ≥ 2`**; not found / not checked → False. A missing drawing counts as an R:R failure. The old computed flag is kept as `f_rr_computed` (internal, hidden, **not** part of status).
- **`status` uses the TV R:R (approved by the user 2026-09-29):** `status=PASS` (and therefore `grok_sync_target` / the `Grok` watchlist sync) = `f_dollar_vol AND f_short_float AND f_no_earnings_14d AND f_history AND f_rr` with `f_rr` from the TradingView drawing. `failed_filters` / `reason` say `rr (no TV drawing read | TV drawing not found | TV R:R x < 2)`. PASS reason: `PASS (TV) entry=… SL=… TP=… R:R=… zone=[…]`.
- **Needs drawing (2026-10-01):** column `needs_drawing` = `f_dollar_vol AND f_short_float AND f_no_earnings_14d AND f_history AND` no TradingView drawing (`tv_found` ≠ yes: not found, **or never read yet** — counts until read) — i.e. the read-target set minus drawn tickers. Smooth streak is **not** required. Informational; **not** part of `status` (PASS / `grok_sync_target` unchanged). Written to `/workspace/stock-screener/grok_needs_drawing_target.{json,txt}` (`EXCHANGE:TICKER`, TV spelling e.g. `NYSE:MOG.A`) by both the daily export and `tv_drawings.py merge`. Dashboard: “needs drawing” checkbox (TradingView group) + amber badge next to the status pill.
- **Chart screenshots (2026-10-01):** for every ticker read with `found=yes`, the nightly read saves a screenshot of the chart **as it is** on the box (e.g. `/workspace/tv_shots/<TICKER>.png`; a read-only screenshot, no clicks on drawings, nothing modified) and attaches it with `python tv_drawings.py upsert <EXCHANGE:TICKER> --zone-top … --zone-bottom … --entry … --sl … --tp … --rr … --screenshot /workspace/tv_shots/<TICKER>.png` (image only: `python tv_drawings.py screenshot <EXCHANGE:TICKER> <path>`). The script resizes to ≤1280px and stores WebP <300KB at `charts/latest/<TICKER>.webp` in the repo (CSV spelling, e.g. `MOG-A`), **overwriting** the previous image (one current image per ticker; no history folder). **Every read gets a screenshot, including not-found charts:** `upsert <EXCHANGE:TICKER> --not-found --screenshot <path>` stores it too (without `--screenshot` the previous image is kept). Store fields `screenshot`, `screenshot_at`, `screenshot_date`; CSV column `tv_screenshot` (via `merge`). Page: `charts.html` (linked from the main dashboard) — one card per drawn ticker with screenshot (click to enlarge), TradingView link, status, TV R:R, zone, entry, SL, TP, distance to zone in ATR, read date; sorted by R:R desc; read-but-not-found tickers with a screenshot follow as dashed cards with a “needs drawing” badge and no R:R/levels; toggles PASS only / near zone only. Then `merge`, and commit `charts/latest/` with the reports.
- **Price near zone (2026-09-30):** `f_near_zone`, `tv_price`, `tv_weekly_atr`, `tv_zone_dist`, `tv_zone_dist_atr` are computed from the cached daily history (`/workspace/hist_cache.pkl`) for `tv_found=yes` rows, both in the nightly export (`report_filters.apply_filters_to_report`) and in `tv_drawings.py merge` (refreshed after the nightly drawing reads). Dashboard: column “dist to zone (ATR)” shows `0.42 ATR`, `in zone` (0) or `not found` (no drawing); optional checkbox “price near zone (≤1 ATR)”. Never part of `status` / `grok_sync_target`.
- **Dashboard:** zone / entry / SL / TP / R:R columns show only TV values (“zone top (TV)”, “entry (TV)”, “SL (TV)”, “TP (TV)”, “TV R:R”); no drawing → the text **“not found”**; these rows always sort to the end in both directions. Default sort: TV R:R desc. Optional filter “TV drawing found” (`tv_found = yes`). The “PASS-equivalent” preset = exactly `status=PASS`.

### Report filters — standalone, ANDed (2026-09-29 restructure)
Rows = **every** ticker the FinViz screener returned for the report day; no row is ever dropped. Every rule is computed for **every** row independently (no short-circuit: a `$vol` fail still gets short float, earnings, R:R, streak, reversals). Missing data → `False` plus a note in `filter_notes`. Code: `report_filters.py` (repo root; copy in `/workspace/stock-screener/`), called by `export_daily_report.py`.

| Filter (bool) | Rule | Value column(s) |
|---|---|---|
| `f_dollar_vol` | 30-day average **dollar** volume (30d avg volume × last close) **≥ $50M** | `dollar_vol_30d`, `avg_vol_30d` |
| `f_short_float` | FinViz short float **< 5%** (missing → False) | `short_float_pct` |
| `f_no_earnings_14d` | next earnings **not** within 14 days (`days_to_earnings ≥ 14`). CSV = as of the report date; dashboard re-evaluates live from `earnings_date`. Unknown or stale date → False | `earnings_date`, `days_to_earnings` |
| `f_history` | **≥ 150 weekly bars** (~3y) | `weekly_bars` |
| `f_rr` | **Now: TradingView drawing found AND `tv_rr ≥ 2`** (see “TradingView drawings”). Legacy, kept as internal `f_rr_computed` (**not** used by `status`): the **whole retest pipeline is ONE filter**: weekly breakout-retest zone found (§3) → entry / SL / TP placed (§4; SL clamped to 0.5–1.0×ATR is part of the calc, **not** a filter) → **R:R ≥ 2**. No setup → False, rr blank. Zone detection is not accurate enough to be its own filter, so it never filters anything implicitly. Computed for any ticker with ≥ 30 weekly bars, independent of `f_history`. | `rr`, informational `zone_lo`, `zone_hi`, `entry`, `sl`, `tp`, `sl_atr_mult`, `atr`, `atrs_from_entry` |
| `f_smooth_streak` | `smooth_streak_weeks ≥ 5` — pure candle rule (no short float / $vol / history gate; those are separate filters) | `smooth_streak_weeks` |
| `f_weekly_reversal` | reversal-shape candle on **any of the last 5 completed weekly bars**, shape-only (no zone gate) | `weekly_reversal_kind`, `weekly_reversal_date` (most recent hit) |
| `f_daily_reversal` | reversal-shape candle on **any of the last 10 completed daily bars**, shape-only (no zone gate) | `daily_reversal_kind`, `daily_reversal_date` (most recent hit) |
| `f_near_zone` | **Price near support zone — TV drawings only, informational, NOT part of `status` / Grok target.** price = latest cached daily close (as of the report date); weekly ATR = ATR(14) on W-FRI weekly bars from the same cache (`stock_screen.atr_series`, the ATR the retest scan uses; the report-date week may be partial); dist = 0 if `tv_zone_bottom ≤ price ≤ tv_zone_top`, else distance to the nearest edge. True iff dist ≤ **1 × weekly ATR** (`CONFIG near_zone_atr_mult`). No drawing (`tv_found` ≠ yes) → **empty** (not False). | `tv_price`, `tv_weekly_atr`, `tv_zone_dist`, `tv_zone_dist_atr` (all empty without a drawing) |

**`status` (back-compat, Grok watchlist):** `PASS` iff `f_dollar_vol AND f_short_float AND f_no_earnings_14d AND f_history AND f_rr` (`f_rr` = TradingView drawing R:R ≥ 2). `failed_filters` lists the core filters that failed. Smooth/reversal filters never change PASS. `reason` = `PASS (TV) …` for a PASS; otherwise the screen's non-geometry text (e.g. `$vol(30d) … < $50M`) + `| FAIL: <core filters>` (old computed-R:R / computed-PASS texts are dropped).

**Reversal shapes** (`weekly_reversal_shapes`, same thresholds on daily bars vs daily ATR14): hammer/pin (lower wick ≥ 0.9×body, close in upper half, lower wick ≥ upper wick, not doji junk); bullish engulfing (green body engulfs prior red body); strong_close (green, close ≥ open+0.5×range or top 40% of range — the old “prior bar near zone” context is dropped in shape-only mode); rejection (lower wick ≥ max(body, 0.35×ATR)). Kind preference per bar: hammer → engulfing → strong_close → rejection. ⚠ Shape-only with these lookbacks is very permissive (2026-09-28: weekly 360/379, daily 377/379); tighten via `--reversal-kinds` or shorter lookbacks.

**Smooth week** (streak): green, OR red with weekly vol < 30-week SMA of weekly vol, OR a reversal shape, OR a doji (body ≤ 10% of range and close ≥ low + 40% of range, any volume). Counted back from the most recent **completed** W-FRI week; cap 104.

**Informational:** `smooth_pullback` (zone-based STRONG pullback, only when a setup exists), `inst_own_pct`, `current_price`, `earnings_known`, `earnings_blackout`, TV/FinViz links. Dashboard recomputes `days_to_earnings` / `earnings_blackout` / `f_no_earnings_14d` live from `earnings_date`; `status` stays as of the report date.

**Parameters — one place: `report_filters.py` `CONFIG`** (core screen numbers are read from `stock_screen.py` so they have one definition). Every key is a CLI flag on both `export_daily_report.py` and `report_filters.py`:

| CONFIG key / flag | Default |
|---|---|
| `dollar_vol_min` / `--dollar-vol-min` | 50,000,000 (`stock_screen.DOLLAR_VOL_MIN`) |
| `avg_vol_days` | 30 |
| `short_float_max_pct` | 5.0 |
| `earnings_blackout_days` | 14 |
| `min_weekly_bars` | 150 |
| `rr_min` | 2.0 |
| `retest_min_weekly_bars` | 30 (min bars to attempt the retest geometry) |
| `min_smooth_streak_weeks` | 5 |
| `smooth_streak_cap_weeks` | 104 |
| `doji_max_body_frac` / `doji_min_close_pos` | 0.10 / 0.40 |
| `daily_reversal_lookback_days` | 10 |
| `weekly_reversal_lookback_weeks` | 5 |
| `reversal_kinds` | `hammer,engulfing,strong_close,rejection` |

SL clamp constants (`stock_screen.SL_ATR_MIN=0.5`, `SL_ATR_MAX=1.0`) are part of the R:R calc, not filters.

**Data sources (cache-first):** price history `/workspace/hist_cache.pkl` (refreshed by `stock_screen.py`); short float / inst own: screen row → `/workspace/stock_screen_universe.json` (written by `stock_screen.py` for **all** tickers) → FinViz quote cache `cache/fv_{T}.json`; earnings: `cache/earn_{T}.json` (date kept until it passes) → universe json → screen/verify row; only dates ≥ report date count.

**Backfill / recompute** an existing report (cache only, no network):
`python report_filters.py --report historical-reports/latest.csv --report historical-reports/YYYY-MM-DD.csv --date YYYY-MM-DD [--min-smooth-streak-weeks 6 …]`

**Dashboard:** one checkbox per filter (grouped Core / Extra, each with its true-count), checked filters ANDed, nothing checked = full FinViz list, live “N of M stocks”, **PASS-equivalent** button = the 5 core filters (matches `status=PASS`). Charts: per-filter pass counts (click toggles the filter), R:R and streak distributions of the current selection. Older dated CSVs load with the columns they have; missing filters are disabled. Checked filters, search text and sort (primary + secondary) persist in browser localStorage (`srs_dashboard_state_v1`) across reloads; the report date is not saved (latest stays default); saved filters missing from the loaded report are ignored; **Clear filters** resets everything and deletes the saved state. **Export TV watchlist (N)** downloads exactly the rows shown (filters + search, current sort) as `scanner_<report-date>_<N>.txt` for TradingView “Import list”: comma-separated `EXCHANGE:TICKER` on one line (TradingView’s documented import format; exchange parsed from each row’s `tradingview_url`); disabled when 0 rows.


## 14. FinViz caches

- **Screener universe**: always live-scraped each run. `screener_tickers.json` is a write-only snapshot for debugging — never reused as input.
- **Quote fundamentals** (short float, inst own): cached in `cache/fv_{TICKER}.json` with TTL **3 days** (`FV_TTL_DAYS`). Stale or incomplete entries are re-fetched.
- **Earnings**: `cache/earn_{TICKER}.json` = `{earnings_date, source, fetched_at}`; the date is reused until it has passed, then refetched (TradingView → Yahoo). Misses retried after 20h (`EARN_MISS_TTL_HOURS`).
