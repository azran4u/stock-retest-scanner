# Stock retest screener — rules

Last updated: 2026-09-19 (full-universe historical reports + GitHub Pages dashboard)  
Owner: Eyal  
Watchlist: TradingView `Grok`  
Tools: FinViz screener (filters) → code scan (yfinance) → TradingView drawings (no live orders)

---

## 0. Roles (split bots)

| Bot | Job |
|-----|-----|
| **Grok Bot** (screener) | FinViz + code filters, pass queue, daily routine code-scan, handoff messages |
| **TV Drawer** (id `3988761`) | Own desktop/browser: weekly drawings + add to `Grok` only |

Never run two TradingView drivers on the same desktop. Grok Bot does not open TradingView for drawing while TV Drawer is the owner.

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

Apply in roughly this order (cheap checks first):

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
- `days_to_earnings` is the integer number of calendar days from today's Asia/Jerusalem date to the next **unreported** earnings date fetched through yfinance.
- If known and `0 <= days_to_earnings < 14`, set `earnings_blackout=true` and **fail/skip it from the PASS queue** (no drawing or `Grok` watchlist entry).
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
- Defined on the **weekly** candle that made the **peak later broken**  
- Zone = range between that candle’s **body** and its **wicks**  
  - Practical snap used in drawings:  
    - **Zone top** ≈ peak candle **wick high** (`High`)  
    - **Zone bottom** ≈ peak candle **body top** (`max(Open, Close)`) — rectangle bottom should **touch the candle’s body top**  
- Example (AMP, teaching example): zone **537.5 – 544.2**

Skip if resistance isn’t clear, price isn’t near the retest, pullback volume isn’t relatively low, or there is no reversal at the zone.

Prefer common stocks over ETFs / CEFs / leveraged products unless the user says otherwise.

---

## 4. Trade geometry (Long Position — drawing only)

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
- Verify columns: ticker, status, current_price, entry, sl, tp, rr, zone_lo, zone_hi, atr, short_float_pct, inst_own_pct, dollar_vol_30d, avg_vol_30d, weekly_bars, days_to_earnings, earnings_known, earnings_blackout, tradingview_url, reason  
- `tradingview_url` best-effort US exchange (`NASDAQ:…` / `NYSE:…`); `MOG-A` → `MOG.A`  
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
- [ ] Zone = peak weekly body-top → wick-high; rectangle to prior high and to today  
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
3. Strict order per ticker: **exchange check → draw zone → draw Long Position → then add to `Grok`**. Never add first.
4. Target watchlist remains **`Grok`**. Do not create other lists. Leave `grok_upload` alone unless the user asks to change it. Always select the **US exchange** in symbol search (see §5) — bare tickers can resolve to foreign listings (e.g. ASB ASX vs NYSE).
5. **Split (active):** teammate **TV Drawer** (agent id `3988761`) owns all TradingView drawings + `Grok` adds on its own desktop. **Grok Bot** (this screener) only runs FinViz/code scans and hands off PASS queues — it must not drive TradingView while TV Drawer exists.

---

## 11. Watchlists

| List | Purpose |
|------|---------|
| **Grok** | Fully processed: drawings done (TV Drawer owns adds after drawings) |
| **Grok queue** | All code-screen PASSes, **no drawings required** — fast visibility while TV Drawer catches up (screener may bulk-add on its own desktop) |
| **grok_upload** | Leave alone unless user asks |

When a new PASS clears the code screen, add it to **Grok queue** promptly (no drawings). Hand the same PASS to TV Drawer for **Grok** drawings.

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

### Columns
Same spirit as the verify table, for every ticker:

`ticker, status, reason, current_price, entry, sl, tp, rr, zone_lo, zone_hi, atr, short_float_pct, inst_own_pct, dollar_vol_30d, avg_vol_30d, weekly_bars, days_to_earnings, earnings_known, earnings_blackout, tradingview_url`

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

Call this at the end of the daily routine after `stock_screen.py` finishes, then commit + push so Pages updates.

### Dashboard URL
https://azran4u.github.io/stock-retest-scanner/

### Fail-reason buckets (dashboard)
Normalize free-text reasons into: `$vol`, `short float`, `history`, `R:R`, `no retest`, `earnings`, `other`.

## 14. FinViz caches

- **Screener universe**: always live-scraped each run. `screener_tickers.json` is a write-only snapshot for debugging — never reused as input.
- **Quote fundamentals** (short float, inst own): cached in `cache/fv_{TICKER}.json` with TTL **3 days** (`FV_TTL_DAYS`). Stale or incomplete entries are re-fetched.
