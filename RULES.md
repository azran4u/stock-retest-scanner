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

- **Peak candle** is chosen by **highest body top** locally: swing highs are local maxima of `max(Open, Close)`, **not** of wick `High`.
- Zone = that peak candle’s body top → wick high:
    - **Zone top (`zone_hi`)** ≈ peak candle **wick high** (`High`)
    - **Zone bottom (`zone_lo`)** ≈ peak candle **body top** (`max(Open, Close)`) — rectangle bottom should **touch the candle’s body top**
- Example (AMP, teaching example): zone **537.5 – 544.2**
- Example (R): use the week with the higher body (e.g. week after a tall-wick spike), not the wick-high week alone.

Skip if resistance isn’t clear, price isn’t near the retest, pullback volume isn’t relatively low, or there is no reversal at the zone.


### 