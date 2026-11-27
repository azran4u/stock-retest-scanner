"""Stan Weinstein stage analysis page (#/stages, Eyal 2026-11-13).

Separate pipeline: its own FinViz screen, its own history cache, its own data file. It never touches the retest
screen, gates, expert zones, drawings or alerts.

Rules = Eyal's masterclass page (Weinstein, 'Secrets for Profiting in Bull and Bear Markets'): weekly (Friday) closes
only, 30-week SMA + its slope, breakout volume >= 2x the 10-week average, Mansfield RS vs the S&P 500 > 0 and rising,
top-down market (SPY / QQQ / IWM) + sector ETF stage, pre-filter (price, liquidity, inst own 25-85%, NYSE / NASDAQ,
no small biotech, >= 40 weeks, no heavy overhead within 20%), stop below the last structural low AND the SMA 150 יום,
R:R >= 3 to the first target, no new Buy-Stop within 10 trading days of earnings (gap-up after a report = wait for a hold). Every threshold is in RULES below and
is shown on the page.

  python -m srs_app.stages             # FinViz -> history -> stages -> app/data/stages.json + stages_spark.json
  python -m srs_app.stages --publish   # ... and upload the changed app data files (srs_app.publish_data)
  python -m srs_app.stages --offline   # recompute from the cached FinViz list + cached history (no network)
  python -m srs_app.stages --publish --alert   # ... + Telegram the Buy-Stop candidates (only when there are any)
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "app" / "data" / "stages.json"
OUT_SPARK = REPO / "app" / "data" / "stages_spark.json"
OUT_CANDLES = REPO / "app" / "data" / "stages_candles"  # weekly OHLCV per stock for the big editable chart (not in git)
CACHE = Path("/workspace/stage_hist_cache.pkl")
UNIVERSE_CACHE = Path("/workspace/cache/stages_universe.json")
SEED_CACHE = Path("/workspace/hist_cache.pkl")  # the retest scanner's yfinance cache: reused (read only) to save downloads

# FinViz custom view (v=152): ticker, company, sector, industry, market cap, inst own, avg volume, price, earnings date
FV_COLS = "1,2,3,4,6,28,30,63,65,68"
FV_FILTERS = "sh_price_o10,sh_avgvol_o100"  # price > $10 (hard minimum), avg daily volume > 100K (= 500K / week)
SCREENS = {ex: f"https://finviz.com/screener/stocks?v=152&f=exch_{code},{FV_FILTERS}&ft=4&o=ticker&c={FV_COLS}"
           for ex, code in (("NYSE", "nyse"), ("NASDAQ", "nasd"))}

BENCH = "^GSPC"  # Mansfield RS benchmark (S&P 500 index)
MARKET = ["SPY", "QQQ", "IWM"]
SECTOR_ETF = {
    "Technology": "XLK", "Financial": "XLF", "Healthcare": "XLV", "Energy": "XLE", "Industrials": "XLI",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP", "Utilities": "XLU", "Basic Materials": "XLB",
    "Real Estate": "XLRE", "Communication Services": "XLC",
}
# Industry ETFs (Eyal 2026-11-16): classified with the same index/sector rules. A stock is GATED on its industry ETF
# when FinViz industry maps cleanly; otherwise on the broad SPDR sector. Thematic names with no clean industry map
# (CIBR / SKYY / BOTZ / LIT) are classified and shown on the industries panel + chart pages, but do not gate stocks.
# ARKK skipped (active thematic fund, not an industry group). XAR / IBB are shown too; stocks map to ITA / XBI.
INDUSTRY_WATCH = [
    "CIBR", "ITA", "XAR", "KRE", "KBE", "XBI", "IBB", "IGV", "SMH",
    "XHB", "ITB", "XRT", "XOP", "OIH", "GDX", "XME", "COPX", "TAN",
    "JETS", "IYT", "PAVE", "URA", "KIE", "IHI", "XPH", "SKYY", "BOTZ", "LIT",
]
INDUSTRY_ETF = {
    "Semiconductors": "SMH", "Semiconductor Equipment & Materials": "SMH",
    "Software - Application": "IGV", "Software - Infrastructure": "IGV",
    "Banks - Regional": "KRE", "Banks - Diversified": "KBE",
    "Biotechnology": "XBI",
    "Drug Manufacturers - General": "XPH", "Drug Manufacturers - Specialty & Generic": "XPH",
    "Medical Devices": "IHI", "Medical Instruments & Supplies": "IHI",
    "Aerospace & Defense": "ITA",
    "Residential Construction": "ITB",
    "Building Products & Equipment": "XHB", "Building Materials": "XHB", "Lumber & Wood Production": "XHB",
    "Specialty Retail": "XRT", "Apparel Retail": "XRT", "Internet Retail": "XRT", "Department Stores": "XRT",
    "Discount Stores": "XRT", "Home Improvement Retail": "XRT", "Grocery Stores": "XRT",
    "Oil & Gas E&P": "XOP",
    "Oil & Gas Equipment & Services": "OIH", "Oil & Gas Drilling": "OIH",
    "Gold": "GDX", "Silver": "GDX", "Other Precious Metals & Mining": "GDX",
    "Copper": "COPX",
    "Steel": "XME", "Other Industrial Metals & Mining": "XME", "Aluminum": "XME",
    "Coking Coal": "XME", "Thermal Coal": "XME",
    "Uranium": "URA",
    "Solar": "TAN",
    "Airlines": "JETS",
    "Trucking": "IYT", "Railroads": "IYT", "Integrated Freight & Logistics": "IYT",
    "Marine Shipping": "IYT", "Airports & Air Services": "IYT",
    "Engineering & Construction": "PAVE",
    "Insurance - Property & Casualty": "KIE", "Insurance - Life": "KIE", "Insurance - Specialty": "KIE",
    "Insurance - Diversified": "KIE", "Insurance Brokers": "KIE", "Insurance - Reinsurance": "KIE",
}
ETF_NAMES = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "XLK": "טכנולוגיה", "XLF": "פיננסים",
             "XLV": "בריאות", "XLE": "אנרגיה", "XLI": "תעשייה", "XLY": "צריכה מחזורית", "XLP": "צריכה בסיסית",
             "XLU": "תשתיות", "XLB": "חומרי גלם", "XLRE": "נדל\"ן", "XLC": "תקשורת",
             "SMH": "שבבים", "IGV": "תוכנה", "CIBR": "סייבר", "SKYY": "מחשוב ענן", "BOTZ": "רובוטיקה",
             "ITA": "תעופה וביטחון", "XAR": "תעופה וביטחון (S&P)", "KRE": "בנקים אזוריים", "KBE": "בנקים",
             "XBI": "ביוטק", "IBB": "ביוטק (Nasdaq)", "XPH": "תרופות", "IHI": "מכשור רפואי",
             "ITB": "בנייה למגורים", "XHB": "בונים ודיור", "XRT": "קמעונאות",
             "XOP": "נפט וגז (E&P)", "OIH": "שירותי נפט", "GDX": "כריית זהב", "XME": "מתכות וכרייה",
             "COPX": "נחושת", "URA": "אורניום", "TAN": "סולארי", "LIT": "ליתיום",
             "JETS": "חברות תעופה", "IYT": "תחבורה", "PAVE": "תשתיות", "KIE": "ביטוח"}

RULES: Dict[str, Any] = {
    "ma_weeks": 30,              # 30-week SMA of weekly closes
    "sma10_weeks": 10,           # 10-week SMA ≈ 50-day (TraderLion early stage-3 warning)
    "slope_lookback_w": 5,       # kept for Buy-Stop / find_breakout (unchanged)
    "slope_flat_pct": 1.0,       # kept for Buy-Stop / find_breakout (unchanged)
    # Stage-engine slope (TraderLion / Eyal 2026-11-27): 3-week % change of the SMA 150 יום,
    # with a same-week turn override so a rollover is "flat" immediately. More responsive
    # than the 5-week ±1% slope_class used by the Buy-Stop screen.
    "sma_slope_w": 3,
    "sma_slope_flat_pct": 0.6,   # |3-week change| <= 0.6% = flat (~0.2%/week)
    "sma_slope_sharp_pct": 1.5,  # 3-week change <= -1.5% and MA not ticking up = sharply down
    "stage_2a_weeks": 6,         # 2a lasts the breakout week + 6 further weeks near the level
    "stage_2a_near_atrs": 2.0,   # stay 2a while close is within 2 weekly ATRs of the breakout
    "light_vol_mult": 1.5,       # retest volume below this is "light"; heavy is vol_mult (2.0)
    "far_below_atrs": 1.0,       # "far below the MA" = more than 1 weekly ATR under it
    "retest_hold_atrs": 0.5,     # a retest "holds slightly above" if close is not >0.5 ATR under the level
    # Daily stage engine (Eyal 2026-11-27, t453u — Stan's recent videos use the daily chart + 150d SMA).
    # ~5 sessions per week: 30W≈150d, 10W≈50d, a 10-week base≈50 days, a 26-week window≈130 days.
    "sma150_days": 150,
    "sma50_days": 50,
    "sma150_slope_d": 20,            # slope = % change of the 150d SMA over 20 sessions
    "sma150_slope_flat_pct": 0.8,    # |20-session change| <= 0.8% = flat
    "sma150_slope_sharp_pct": 2.0,   # 20-session change <= -2.0% and MA not ticking up = sharply down
    "pivot_d": 10,                   # daily swing = extreme vs 10 sessions on each side (≈ a 2-week weekly pivot)
    "idx_pivot_d": 13,               # slightly wider confirmation for index / sector ETFs
    "base_window_d": 130,            # ~26 weeks of sessions
    "min_base_d": 50,                # ~10 weeks
    "range_max_d": 260,              # ~52 weeks
    "stage_2a_days": 30,             # breakout week-equivalent: ~6 weeks of sessions
    "idx_top_d": 50,                 # no new high of the advance for ~10 weeks
    "vol_avg_d": 50,                 # breakout volume vs 50-day average daily volume (TraderLion: 2–3x)
    "prior_trend_d": 260,
    "idx_consistent_d": 25,          # 'consistently above' the 150d = >= 20 of the last 25 daily closes
    "idx_consistent_n_d": 20,
    "prior_trend_w": 52,         # flat MA: stage 1 if the last non-flat slope (within 52w) was declining, 3 if rising
    "rs_ma_weeks": 52,           # Mansfield RS = ((stock/SPX) / SMA52(stock/SPX) - 1) * 100
    "rs_rising_w": 4,            # RS rising = RS now > RS 4 weeks ago
    "pivot_w": 2,                # swing high / low = higher / lower than 2 weekly bars on each side
    "sig_pivot_w": 8,            # overhead resistance = SIGNIFICANT weekly swing high (highest high 8 weekly bars on each side)
    "target_min_gap_pct": 2.0,   # a level counts as overhead only when > 2% above the entry
    "base_window_w": 26,         # base resistance = highest weekly high of the 26 weeks before the breakout / now
    "min_base_w": 10,            # base: resistance set >= 10 weeks earlier AND >= 10 weekly closes at / under it
    "bo_max_weeks_ago": 3,       # breakout week = one of the last 4 completed weeks (0-3 weeks ago; entry window 1-3 weeks)
    "vol_avg_w": 10,             # breakout volume vs average weekly volume of the 10 weeks before it
    "vol_mult": 2.0,             # >= 2.0x  (< 1.5x = fakeout, avoid); in-base volume is never penalised
    "strong_close": 0.75,        # A+ breakout: close in the top 25% of the breakout week's range
    "buy_zone_pct": 10.0,        # don't chase: last close <= breakout level + 10% ...
    "max_pct_above_ma": 25.0,    # ... AND <= SMA 150 יום + 25% (Eyal 2026-11-14, XERS example); else 'רחוקה מדי / אל תרדוף'
    "range_max_w": 52,           # stage 1 / 3 trading range = high / low since the stage began (10-52 weeks)
    "extended_pct": 35.0,        # stage 2 'over-extended' = close > 35% above the SMA 150 יום (partial exit zone)
    "stop_buffer_pct": 0.7,      # (old 2026-11-14 rule, kept for reference only; replaced by stop_margin_pct 2026-11-16)
    "stop_margin_pct": 0.75,     # Eyal 2026-11-16: stop 0.75% under the LOWER of (SMA 150 יום, base's last unbroken low) ...
    "stop_margin_max_pct": 1.0,  # ... or just under a round number when that stays within 1% of the anchor
    "stop_round_tick": 0.05,     # 'just under' the round number = $0.05 below it
    "max_stop_pct": 10.0,        # stop farther than 10% under the entry = 'SL רחב מדי' flag (info only, never disqualifies)
    "buy_stop_buf_pct": 0.5,     # Buy-Stop = base resistance + 0.5% (min $0.05) -- 'slightly above the ceiling'
    "buy_stop_min_buf": 0.05,
    "pre_bo_pct": 5.0,           # pre-breakout Buy-Stop setup: last close within 5% under the base resistance
    "min_rr": 2.5,               # R:R from the Buy-Stop entry to the nearest overhead resistance >= 2.5 (Eyal 2026-11-14)
    "overhead_w": 104,           # overhead resistance = significant swing highs of the last 2 years (104 weeks)
    "cong_min_w": 5,             # info: trading block = >= 5 weekly closes inside a 3% band above the entry
    "cong_band_pct": 3.0,
    "sector_allow_stage3": False,
    # index / sector ETF classifier (Eyal 2026-11-15, classify_index)
    "idx_pivot_w": 3,            # swing high / low of an index = extreme of 3 weekly bars on each side (HH/HL vs LH/LL)
    "idx_consistent_w": 10,      # 'consistently above' = >= 8 of the last 10 weekly closes above the 30W SMA;
    "idx_consistent_n": 8,       # 'consistently below' = <= 2 of 10 above; otherwise 'crossing back and forth'
    "idx_top_w": 10,             # stage 2 -> 3: the SMA lost its rise and no new high of the advance for 10 weeks
    "mkt_block_stages": [3, 4],  # rule 3: SPY in stage 3 or 4 -> no new long Buy-Stop (was: only stage 4)  # sector ETF in stage 3 fails (it is neither 'clear stage 2' nor 'late stage 1')
    # short side (Stan Weinstein short-selling rules, mirror of long Buy-Stop)
    "sell_stop_buf_pct": 0.5,    # Sell-Stop = base support - 0.5% (min $0.05) -- mirror of buy_stop_buf_pct
    "sell_stop_min_buf": 0.05,
    "sell_zone_pct": 10.0,       # don't chase shorts: close / Sell-Stop within 10% below breakdown level ...
    "max_pct_below_ma": 25.0,    # ... AND within 25% below SMA 150 יום
    "short_mkt_allow_stages": [3, 4],     # SPY in stage 3 or 4 permits shorts; stage 1 / stage 2 (incl. 2-weak) block
    "short_mkt_allow_2weak": False,       # 2-weak still has a rising SMA 150 יום -> wait for stage 3 or 4
    "short_sector_allow_stages": [3, 4],  # sector / industry ETF in stage 3 or 4 permits shorts; never clear stage 2
    "short_float_max_pct": 10.0,          # avoid heavily shorted names (>= 10% short float) when data exists
    "cash_etf_atr_pct_max": 1.0,          # hard pre-filter: cash / money-market / short-bond ETFs out
    "earn_td": 10,               # no new Buy-Stop when the report session is within the next 10 trading days (Eyal 2026-11-14:
                                 # the report week AND the week before; an after-close report counts on the next session)
    "earn_est_days": 91,         # FinViz has only a PAST date -> next report estimated at +13 weeks ('משוער'), blocks too
    "post_earn_td": 5,           # a report in the last 5 sessions -> post-earnings rules (gap-up / back to the Buy-Stop)
    "gap_min_pct": 2.0,          # post-earnings gap-up = open >= 2% above the prior close, close above the resistance,
    "gap_vol_mult": 2.0,         # ... on >= 2x the 20-day average volume -> don't chase, wait for a hold / mini-base
    "gap_vol_avg_d": 20,
    "mini_base_d": 3,            # ... candidate again after >= 3 sessions after the gap day all closing above the level
    "min_price": 15.0, "hard_min_price": 10.0,
    "min_dollar_vol_m": 50.0, "dollar_vol_days": 50, "dollar_vol_weeks": 10,  # Eyal 2026-11-16 (VBNK): avg daily $vol >= $50M, dropped BEFORE classification (indexes / sector ETFs exempt)
    "min_week_vol": 500_000,  # FinViz screen only (avg daily share volume > 100K)
    "inst_lo": 25.0, "inst_hi": 85.0, "min_weeks": 156, "biotech_cap_b": 2.0,  # min_weeks: >= 3 years of weekly bars (Eyal 2026-11-15, IEAG), dropped BEFORE classification
    "risk_usd": 55.0, "account_usd": 5000.0, "position_cap_pct": 15.0,
    "spark_weeks": 104, "candle_weeks": 160,
}

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


# ----------------------------------------------------------------------------------------------- FinViz universe
def _num(txt: str) -> Optional[float]:
    t = (txt or "").strip().replace(",", "")
    if not t or t == "-":
        return None
    mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(t[-1].upper())
    if mult:
        t = t[:-1]
    t = t.rstrip("%")
    try:
        return float(t) * (mult or 1)
    except ValueError:
        return None


def parse_earn(txt: str, today: date) -> Optional[str]:
    """FinViz 'Nov 20/a' (no year) -> ISO date, the year chosen so the date lies within ~6 months of today."""
    m = re.match(r"([A-Za-z]{3})\s+(\d{1,2})", txt or "")
    if not m:
        return None
    try:
        d = datetime.strptime(f"{m.group(1)} {m.group(2)} {today.year}", "%b %d %Y").date()
    except ValueError:
        return None
    if (d - today).days > 183:
        d = d.replace(year=d.year - 1)
    elif (today - d).days > 183:
        d = d.replace(year=d.year + 1)
    return d.isoformat()


def earn_timing(txt: str) -> Optional[str]:
    """FinViz 'Nov 20/a' -> 'a' (after close) / 'b' (before open) / None."""
    m = re.search(r"/\s*([ab])\b", txt or "")
    return m.group(1) if m else None


def _fv_page(sess, url: str):
    from bs4 import BeautifulSoup
    for attempt in range(4):
        try:
            r = sess.get(url, timeout=30)
            if r.status_code in (429, 503):
                time.sleep(5 * (attempt + 1)); continue
            r.raise_for_status()
            break
        except Exception as e:  # noqa: BLE001
            print(f"[stages finviz] {url}: {e}")
            time.sleep(3)
    else:
        return None, None
    m = re.search(r"#1 / (\d+)", r.text)
    total = int(m.group(1)) if m else None
    soup = BeautifulSoup(r.text, "lxml")
    cols: Dict[str, list] = {}
    for c in soup.find_all(attrs={"role": "gridcell", "data-column-id": True}):
        cols.setdefault(c["data-column-id"], []).append(c)
    out = []
    tk = cols.get("ticker", [])
    for i, c in enumerate(tk):
        t = c.get("data-ticker") or c.get_text(strip=True)
        if not t:
            continue
        g = lambda k: (cols[k][i].get_text(strip=True) if k in cols and len(cols[k]) == len(tk) else "")  # noqa: E731
        out.append({"ticker": t, "company": g("company"), "sector": g("sector"), "industry": g("industry"),
                    "mcap": _num(g("marketCap")), "inst_own": _num(g("instOwn")), "short_float": _num(g("shortInterestShare")),
                    "avg_vol": _num(g("averageVolume")), "fv_price": _num(g("price")), "earn_raw": g("earningsDate")})
    return out, total


def fetch_universe() -> Dict[str, Any]:
    import requests
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    rows: Dict[str, Dict[str, Any]] = {}
    totals = {}
    for ex, base in SCREENS.items():
        seen = set()
        total = None
        for order in ("ticker", "-ticker"):  # FinViz pages only up to row 1000: read ascending, then descending
            url0 = base.replace("o=ticker", f"o={order}")
            for page in range(50):
                rr, tot = _fv_page(sess, url0 + (f"&r={1 + page * 20}" if page else ""))
                if rr is None:
                    break
                total = total or tot
                new = [x for x in rr if x["ticker"] not in seen]
                for x in rr:
                    seen.add(x["ticker"])
                    x["exchange"] = ex
                    rows[x["ticker"]] = x
                if not new or len(rr) < 20:
                    break
                time.sleep(0.4)
            if total is None or len(seen) >= total:
                break
        totals[ex] = {"total": total, "read": len(seen)}
        print(f"[stages finviz] {ex}: {len(seen)}/{total}")
    doc = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "screens": SCREENS, "totals": totals,
           "rows": rows}
    UNIVERSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    UNIVERSE_CACHE.write_text(json.dumps(doc))
    return doc


# ----------------------------------------------------------------------------------------------- history
def load_history(tickers: List[str], offline: bool = False) -> Dict[str, pd.DataFrame]:
    import stock_screen as ss  # repo root module: reuse its yfinance download + rolling refresh
    hm: Dict[str, pd.DataFrame] = pd.read_pickle(CACHE) if CACHE.exists() else {}
    if offline:
        return hm
    missing = [t for t in tickers if t not in hm or hm[t] is None or getattr(hm[t], "empty", True)]
    if missing and SEED_CACHE.exists():
        seed = pd.read_pickle(SEED_CACHE)
        for t in missing:
            df = seed.get(t)
            if df is not None and not getattr(df, "empty", True):
                hm[t] = df
        del seed
        print(f"[stages] seeded {sum(1 for t in missing if t in hm)} / {len(missing)} missing tickers from {SEED_CACHE}")
    hm = ss.refresh_hist_map(hm, tickers)
    keep = set(tickers)
    hm = {t: df for t, df in hm.items() if t in keep}
    pd.to_pickle(hm, CACHE)
    return hm


def weekly(daily: pd.DataFrame, last_session: pd.Timestamp) -> pd.DataFrame:
    """Completed W-FRI weeks only (Weinstein: Friday closes). A week counts once its Friday <= last completed session."""
    d = daily.copy()
    d.index = pd.to_datetime(d.index)
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    d = d[d.index.normalize() <= last_session]
    w = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    return w[w.index <= last_session]


# ----------------------------------------------------------------------------------------------- indicators
def pivots(x: np.ndarray, k: int, high: bool) -> List[int]:
    out = []
    for i in range(k, len(x) - k):
        win = x[i - k:i + k + 1]
        if (high and x[i] == win.max() and x[i] > x[i - k:i].max()) or (not high and x[i] == win.min() and x[i] < x[i - k:i].min()):
            out.append(i)
    return out


def slope_class(ma: np.ndarray, i: int, R=RULES) -> Tuple[Optional[str], Optional[float]]:
    j = i - R["slope_lookback_w"]
    if j < 0 or np.isnan(ma[i]) or np.isnan(ma[j]) or ma[j] <= 0:
        return None, None
    s = (ma[i] / ma[j] - 1) * 100
    return ("up" if s > R["slope_flat_pct"] else "down" if s < -R["slope_flat_pct"] else "flat"), s




def _stage_R(R=RULES) -> Dict[str, Any]:
    """Bar-count keys for the daily stage engine, mapped onto the names stage_path / _range use.

    Stage detection is daily (Eyal t453u, 2026-11-27). Weekly RULES used by find_breakout
    and the Buy-Stop plan (26-week base, weekly 30W SMA, 5-week slope_class) are left unchanged.
    """
    d = dict(R)
    d["ma_weeks"] = int(R.get("sma150_days", 150))
    d["sma10_weeks"] = int(R.get("sma50_days", 50))
    d["sma_slope_w"] = int(R.get("sma150_slope_d", 20))
    d["sma_slope_flat_pct"] = float(R.get("sma150_slope_flat_pct", 0.8))
    d["sma_slope_sharp_pct"] = float(R.get("sma150_slope_sharp_pct", 2.0))
    d["pivot_w"] = int(R.get("pivot_d", 10))
    d["idx_pivot_w"] = int(R.get("idx_pivot_d", 13))
    d["base_window_w"] = int(R.get("base_window_d", 130))
    d["min_base_w"] = int(R.get("min_base_d", 50))
    d["range_max_w"] = int(R.get("range_max_d", 260))
    d["stage_2a_weeks"] = int(R.get("stage_2a_days", 30))
    d["idx_top_w"] = int(R.get("idx_top_d", 50))
    d["vol_avg_w"] = int(R.get("vol_avg_d", 50))
    d["prior_trend_w"] = int(R.get("prior_trend_d", 260))
    d["idx_consistent_w"] = int(R.get("idx_consistent_d", 25))
    d["idx_consistent_n"] = int(R.get("idx_consistent_n_d", 20))
    return d


def sma_slope(ma: np.ndarray, i: int, R=None) -> Tuple[Optional[str], Optional[float], bool]:
    """Responsive SMA 150 יום slope for the stage engine (TraderLion / Eyal 2026-11-27).

    3-week percent change of the SMA 150 יום, with a same-week turn override: a MA that
    already ticked down this week is never 'up', and a MA that ticked up is never
    'down'. So a rollover is 'flat' immediately, instead of waiting for a 5-week
    lookback to flip. 'sharply down' = 3-week change <= -sma_slope_sharp_pct and
    the MA did not tick up this week.

    The older slope_class() (5-week, ±1%) is left unchanged for Buy-Stop / find_breakout.
    """
    if R is None:
        from srs_app.stages import RULES as R
    lb = int(R.get("sma_slope_w", 3))
    flat = float(R.get("sma_slope_flat_pct", 0.6))
    sharp = float(R.get("sma_slope_sharp_pct", 1.5))
    j = i - lb
    if j < 0 or np.isnan(ma[i]) or np.isnan(ma[j]) or ma[j] <= 0:
        return None, None, False
    s = (ma[i] / ma[j] - 1) * 100
    cls = "up" if s > flat else "down" if s < -flat else "flat"
    ticked_down = i >= 1 and not np.isnan(ma[i - 1]) and ma[i] < ma[i - 1]
    ticked_up = i >= 1 and not np.isnan(ma[i - 1]) and ma[i] > ma[i - 1]
    if cls == "up" and ticked_down:
        cls = "flat"
    elif cls == "down" and ticked_up:
        cls = "flat"
    sharp_down = bool(s <= -sharp and not ticked_up)
    return cls, s, sharp_down


def _week_vol_ratio(v: np.ndarray, i: int, avg_w: int) -> Optional[float]:
    if i < avg_w or avg_w <= 0:
        return None
    avg = float(np.mean(v[i - avg_w:i]))
    if avg <= 0:
        return None
    return float(v[i]) / avg


def _wilder_atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    atr = np.full(len(c), np.nan, dtype=float)
    if len(c) < n + 1:
        return atr
    tr = np.empty(len(c))
    tr[0] = float(h[0] - l[0])
    for i in range(1, len(c)):
        tr[i] = max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
    atr[n] = float(tr[1:n + 1].mean())
    for i in range(n + 1, len(c)):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def _far_below(close: float, ma: float, atr: float, R) -> bool:
    if ma is None or np.isnan(ma) or close is None or np.isnan(close):
        return False
    k = float(R.get("far_below_atrs", 1.0))
    if atr is not None and not np.isnan(atr) and atr > 0:
        return bool(close < ma - k * atr)
    return bool(close < ma * 0.95)


def _atr_or_pct(level: float, atr: float, n_atr: float, pct: float = 0.05) -> float:
    if atr is not None and not np.isnan(atr) and atr > 0:
        return n_atr * atr
    return abs(level) * pct


def mansfield(close: pd.Series, bench: pd.Series, R=RULES) -> pd.Series:
    b = bench.reindex(close.index).ffill()
    ratio = close / b
    return (ratio / ratio.rolling(R["rs_ma_weeks"]).mean() - 1) * 100


def _f(x, d=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), d)


def _base_count(c: np.ndarray, end: int, res: float) -> int:
    n = 0
    for j in range(end, max(-1, end - 105), -1):
        if c[j] <= res:
            n += 1
        else:
            break
    return n


def find_breakout(w: pd.DataFrame, ma: np.ndarray, R=RULES) -> Optional[Dict[str, Any]]:
    """Earliest week b among the last bo_max_weeks_ago+1 completed weeks whose close broke above the base resistance
    (highest high of the base_window_w weeks before b), the resistance set >= min_base_w weeks before b with >= min_base_w
    closes at / under it (a real base: stage 1 -> 2 or a stage-2 continuation base), close > SMA 150 יום and the SMA not
    declining. Volume / holding are reported, not required here."""
    h, c, v = w["High"].values, w["Close"].values, w["Volume"].values
    n = len(w)
    for b in range(max(R["base_window_w"], n - 1 - R["bo_max_weeks_ago"]), n):
        seg = h[b - R["base_window_w"]:b]
        res = seg.max()
        top_i = b - R["base_window_w"] + int(np.argmax(seg))
        if not (c[b] > res and c[b] > ma[b]):
            continue
        sc, _ = slope_class(ma, b, R)
        if sc not in ("up", "flat"):
            continue
        base = _base_count(c, b - 1, res)
        if base < R["min_base_w"] or (b - top_i) < R["min_base_w"]:
            continue
        av = v[max(0, b - R["vol_avg_w"]):b].mean() if b > 0 else np.nan
        rng = h[b] - w["Low"].values[b]
        lo_base = w["Low"].values[b - min(base, R["base_window_w"]):b].min()
        return {"week": w.index[b].strftime("%Y-%m-%d"), "idx": b, "weeks_ago": n - 1 - b, "level": float(res),
                "base_weeks": base, "base_low": float(lo_base), "stop_low": float(w["Low"].values[top_i:b].min()), "res_week": w.index[top_i].strftime("%Y-%m-%d"),
                "vol_ratio": float(v[b] / av) if av and av > 0 else None,
                "close_pos": float((c[b] - w["Low"].values[b]) / rng) if rng > 0 else None}
    return None


def base_now(w: pd.DataFrame, R=RULES) -> Optional[Dict[str, Any]]:
    """Current base under its resistance (pre-breakout Buy-Stop setup): resistance = highest high of the last
    base_window_w weeks, set >= min_base_w weeks ago, with >= min_base_w closes at / under it."""
    h, l, c = w["High"].values, w["Low"].values, w["Close"].values
    n = len(w)
    if n < R["base_window_w"]:
        return None
    seg = h[n - R["base_window_w"]:]
    top_i = n - R["base_window_w"] + int(np.argmax(seg))
    top = float(seg.max())
    cnt = _base_count(c, n - 1, top)
    blo = float(l[n - min(max(cnt, 1), R["base_window_w"]):].min())
    # stop_low (Eyal 2026-11-16, anchor B): the floor of the CURRENT base = lowest low since the base's ceiling week
    return {"top": top, "low": blo, "stop_low": float(l[top_i:].min()), "weeks": cnt, "top_week": w.index[top_i].strftime("%Y-%m-%d"),
            "since_top_w": n - 1 - top_i, "mature": bool(cnt >= R["min_base_w"] and (n - 1 - top_i) >= R["min_base_w"])}


def buy_stop_price(level: float, R=RULES) -> float:
    return level + max(level * R["buy_stop_buf_pct"] / 100, R["buy_stop_min_buf"])


def overhead_scan(w: pd.DataFrame, entry: float, R=RULES) -> Dict[str, Any]:
    """Overhead resistance (Eyal 2026-11-14): significant weekly swing highs (sig_pivot_w bars each side) of the last
    overhead_w weeks above entry + target_min_gap_pct, plus the highest high of the window when older than sig_pivot_w
    weeks (a ceiling whose own pivot lies before the window). Nearest = the first target. None -> 'open sky'.
    Info: nearest trading block (>= cong_min_w weekly closes inside a cong_band_pct band) above the entry."""
    h, c = w["High"].values, w["Close"].values
    n = len(w)
    lo_i = max(0, n - R["overhead_w"])
    thr = entry * (1 + R["target_min_gap_pct"] / 100)
    lv = [float(h[i]) for i in pivots(h, R["sig_pivot_w"], True) if i >= lo_i and h[i] > thr]
    old = h[lo_i:max(lo_i, n - R["sig_pivot_w"])]
    if len(old) and old.max() > thr:
        lv.append(float(old.max()))
    nearest = min(lv) if lv else None
    cs = sorted(float(x) for x in c[lo_i:] if x > thr)
    cong = next((x for x in cs if sum(1 for y in cs if x <= y <= x * (1 + R["cong_band_pct"] / 100)) >= R["cong_min_w"]), None)
    lv_u: List[float] = []
    for x in sorted(lv):  # the nearest few distinct levels (chart lines; Eyal 2026-11-14)
        if not lv_u or x > lv_u[-1] * 1.01:
            lv_u.append(x)
    return {"overhead": nearest, "levels": lv_u[:4], "overhead_pct": (nearest / entry - 1) * 100 if nearest else None, "open_sky": nearest is None,
            "ath": bool(h.max() <= thr), "cong": cong, "hi2y": float(h[lo_i:].max())}


def round_step(price: float) -> float:
    """'Round number' grid for the stop snap: < $10 -> $0.50, < $100 -> $1, < $1000 -> $5, else $10."""
    return 0.5 if price < 10 else 1.0 if price < 100 else 5.0 if price < 1000 else 10.0


def stop_below(anchor: float, R=RULES) -> float:
    """Stop under an anchor (Eyal 2026-11-16): anchor x (1 - stop_margin_pct) (0.75%, inside the 0.5%-1% band); when a
    round number sits just under the anchor and 'round number - stop_round_tick' is still within stop_margin_max_pct of
    the anchor, the stop goes just under that round number instead (whichever is lower)."""
    stop = anchor * (1 - R["stop_margin_pct"] / 100)
    st = round_step(anchor)
    rn = math.floor(anchor / st) * st
    if rn >= anchor:  # anchor exactly on the grid -> the round number IS the anchor level
        rn = anchor
    alt = rn - R["stop_round_tick"]
    if anchor * (1 - R["stop_margin_max_pct"] / 100) <= alt < stop:
        stop = alt
    return stop


def stop_anchors(w: pd.DataFrame, ma_now: float, entry: float, base_low: Optional[float], R=RULES) -> Dict[str, Any]:
    """Initial stop (Eyal 2026-11-16, replaces the 'never under the SMA' rule). Anchor A = the SMA 150 יום; anchor B = the
    last significant low of the current base that has not been broken = the floor of the current base (lowest low since
    the base's ceiling week; stage-1 range = the box floor; when a later week undercut it, that newer lower low). Stop under the LOWER of the two (stop_below):
      B above the SMA -> under the SMA ('ma');  B below the SMA -> under B ('low').
    'Too far': B below the SMA, that stop > max_stop_pct (10%) under the entry and the SMA rising -> under the most recent
    unbroken HIGHER low (weekly pivot, pivot_w bars each side) formed after B, below the SMA and the entry ('hl'), if any."""
    l = w["Low"].values
    n = len(w)
    b, bi = None, None
    if base_low is not None and base_low < entry:
        lo_i = max(0, n - 105)
        hits = [i for i in range(lo_i, n) if abs(l[i] - base_low) <= max(0.005, base_low * 1e-5)]
        bi = hits[-1] if hits else None
        b = float(base_low)
        if bi is not None and bi < n - 1 and l[bi + 1:].min() < b:  # broken later -> the newer lower low is the anchor
            bi = bi + 1 + int(np.argmin(l[bi + 1:])); b = float(l[bi])
    if b is None or b >= ma_now:
        return {"stop": stop_below(ma_now, R), "basis": "ma", "anchor": ma_now, "b": b, "hl": None}
    stop = stop_below(b, R)
    out = {"stop": stop, "basis": "low", "anchor": b, "b": b, "hl": None}
    ma = w["Close"].rolling(R["ma_weeks"]).mean().values
    sc, _ = slope_class(ma, n - 1, R)
    if (entry - stop) / entry * 100 > R["max_stop_pct"] and sc == "up" and bi is not None:
        hls = [i for i in pivots(l, R["pivot_w"], False)
               if i > bi and b < l[i] < min(ma_now, entry) and (i == n - 1 or l[i] <= l[i + 1:].min())]  # an equal low = held
        if hls:
            hv = float(l[hls[-1]])
            out.update(stop=stop_below(hv, R), basis="hl", anchor=hv, hl=hv)
    return out


def trade_levels(w: pd.DataFrame, ma_now: float, entry: float, resistance: Optional[float], base_low: Optional[float],
                 R=RULES) -> Dict[str, Any]:
    """Stop (Eyal 2026-11-16) = under the lower of the SMA 150 יום and the base's last unbroken low (stop_anchors); first
    target = nearest overhead resistance of the last 2 years (significant weekly swing high); none = open sky -> target =
    entry + min_rr x risk (R:R exactly 2.5, Eyal 2026-11-14)."""
    sa = stop_anchors(w, ma_now, entry, base_low, R)
    stop, basis = sa["stop"], sa["basis"]
    swing_low = sa["anchor"] if basis != "ma" else sa["b"]  # the red line = anchor B (the higher low when used)
    ov = overhead_scan(w, entry, R)
    risk = entry - stop
    target, tsrc = (ov["overhead"], "overhead") if ov["overhead"] else (None, None)
    if target is None and risk > 0:  # open sky (Eyal 2026-11-14): trade bar at exactly R:R = min_rr
        target, tsrc = entry + R["min_rr"] * risk, "open_sky"
    rr = (target - entry) / risk if (target and risk > 0 and target > entry) else None
    shares = int(R["risk_usd"] // risk) if risk > 0 else None
    stop_pct = risk / entry * 100 if entry else None
    return {"entry": _f(entry), "stop": _f(stop), "stop_basis": basis, "swing_low": _f(swing_low), "anchor_b": _f(sa["b"]),
            "stop_anchor": _f(sa["anchor"]), "target": _f(target), "target_src": tsrc,
            "risk_pct": _f(stop_pct, 1), "stop_wide": bool(stop_pct is not None and stop_pct > R["max_stop_pct"]),
            "rr": _f(rr), "shares": shares, "pos_usd": _f(shares * entry, 0) if shares else None,
            "overhead": _f(ov["overhead"]), "overhead_pct": _f(ov["overhead_pct"], 1), "open_sky": ov["open_sky"],
            "ath": ov["ath"], "cong": _f(ov["cong"]), "hi2y": _f(ov["hi2y"]), "ov_levels": [_f(x) for x in ov["levels"]]}


def _base_count_above(c: np.ndarray, end: int, sup: float) -> int:
    n = 0
    for j in range(end, max(-1, end - 105), -1):
        if c[j] >= sup:
            n += 1
        else:
            break
    return n


def find_breakdown(w: pd.DataFrame, ma: np.ndarray, R=RULES) -> Optional[Dict[str, Any]]:
    """Earliest week b among the last bo_max_weeks_ago+1 completed weeks whose close broke below base support
    (lowest low of base_window_w weeks before b), the support set >= min_base_w weeks before b with >= min_base_w
    closes at/above it, close < SMA 150 יום and SMA flat or declining. Volume on breakdown is reported (not required)."""
    h, l, c, v = w["High"].values, w["Low"].values, w["Close"].values, w["Volume"].values
    n = len(w)
    for b in range(max(R["base_window_w"], n - 1 - R["bo_max_weeks_ago"]), n):
        seg = l[b - R["base_window_w"]:b]
        sup = seg.min()
        bot_i = b - R["base_window_w"] + int(np.argmin(seg))
        if not (c[b] < sup and c[b] < ma[b]):
            continue
        sc, _ = slope_class(ma, b, R)
        if sc not in ("down", "flat"):
            continue
        base = _base_count_above(c, b - 1, sup)
        if base < R["min_base_w"] or (b - bot_i) < R["min_base_w"]:
            continue
        av = v[max(0, b - R["vol_avg_w"]):b].mean() if b > 0 else np.nan
        rng = h[b] - l[b]
        hi_base = h[b - min(base, R["base_window_w"]):b].max()
        return {"week": w.index[b].strftime("%Y-%m-%d"), "idx": b, "weeks_ago": n - 1 - b, "level": float(sup),
                "base_weeks": base, "base_high": float(hi_base), "stop_high": float(h[bot_i:b].max()),
                "sup_week": w.index[bot_i].strftime("%Y-%m-%d"),
                "vol_ratio": float(v[b] / av) if av and av > 0 else None,
                "close_pos": float((c[b] - l[b]) / rng) if rng > 0 else None}
    return None


def short_base_now(w: pd.DataFrame, R=RULES) -> Optional[Dict[str, Any]]:
    """Current base above its support (pre-breakdown Sell-Stop setup): support = lowest low of the last
    base_window_w weeks, set >= min_base_w weeks ago, with >= min_base_w closes at / above it."""
    h, l, c = w["High"].values, w["Low"].values, w["Close"].values
    n = len(w)
    if n < R["base_window_w"]:
        return None
    seg = l[n - R["base_window_w"]:]
    bot_i = n - R["base_window_w"] + int(np.argmin(seg))
    floor = float(seg.min())
    cnt = _base_count_above(c, n - 1, floor)
    bhi = float(h[n - min(max(cnt, 1), R["base_window_w"]):].max())
    return {"floor": floor, "top": bhi, "stop_high": float(h[bot_i:].max()), "weeks": cnt,
            "bot_week": w.index[bot_i].strftime("%Y-%m-%d"), "since_bot_w": n - 1 - bot_i,
            "mature": bool(cnt >= R["min_base_w"] and (n - 1 - bot_i) >= R["min_base_w"])}


def sell_stop_price(level: float, R=RULES) -> float:
    return max(0.01, level - max(level * R["sell_stop_buf_pct"] / 100, R["sell_stop_min_buf"]))


def support_scan(w: pd.DataFrame, entry: float, R=RULES) -> Dict[str, Any]:
    """Downside support targets (mirror of overhead_scan): significant weekly swing lows (sig_pivot_w bars each side)
    of the last overhead_w weeks below entry - target_min_gap_pct, plus the lowest low of the window when older than
    sig_pivot_w weeks. Nearest (highest below entry) = first target. None -> 'open_sky' (free fall)."""
    l, c = w["Low"].values, w["Close"].values
    n = len(w)
    lo_i = max(0, n - R["overhead_w"])
    thr = entry * (1 - R["target_min_gap_pct"] / 100)
    lv = [float(l[i]) for i in pivots(l, R["sig_pivot_w"], False) if i >= lo_i and 0 < l[i] < thr]
    old = l[lo_i:max(lo_i, n - R["sig_pivot_w"])]
    if len(old) and 0 < old.min() < thr:
        lv.append(float(old.min()))
    nearest = max(lv) if lv else None
    cs = sorted((float(x) for x in c[lo_i:] if 0 < x < thr), reverse=True)
    cong = next((x for x in cs if sum(1 for y in cs if x * (1 - R["cong_band_pct"] / 100) <= y <= x) >= R["cong_min_w"]), None)
    lv_u: List[float] = []
    for x in sorted(lv, reverse=True):
        if not lv_u or x < lv_u[-1] * 0.99:
            lv_u.append(x)
    return {"support": nearest, "levels": lv_u[:4], "support_pct": (1 - nearest / entry) * 100 if nearest else None,
            "open_sky": nearest is None, "atl": bool(l.min() >= thr), "cong": cong, "lo2y": float(l[lo_i:].min())}


def stop_above(anchor: float, R=RULES) -> float:
    """Protective Buy-Stop above an anchor (mirror of stop_below): anchor x (1 + stop_margin_pct) (0.75%); when a round
    number sits just above the anchor and 'round number + stop_round_tick' is still within stop_margin_max_pct (1%) of
    the anchor, the stop goes just above that round number instead (whichever is higher)."""
    stop = anchor * (1 + R["stop_margin_pct"] / 100)
    st = round_step(anchor)
    rn = math.ceil(anchor / st) * st
    if rn <= anchor:
        rn = anchor
    alt = rn + R["stop_round_tick"]
    if stop < alt <= anchor * (1 + R["stop_margin_max_pct"] / 100):
        stop = alt
    return stop


def short_stop_anchors(w: pd.DataFrame, ma_now: float, entry: float, base_high: Optional[float], R=RULES) -> Dict[str, Any]:
    """Initial protective Buy-Stop for shorts (exact mirror of stop_anchors, Eyal 2026-11-16):
    Anchor A = SMA 150 יום; Anchor B = last unbroken rally high of the current top/base (if exceeded later, that newer
    higher high). Stop above the HIGHER of the two (stop_above):
      B <= SMA -> above SMA ('ma');  B > SMA -> above B ('high').
    'Too far': B > SMA, stop > max_stop_pct (10%) above entry and SMA declining -> above the most recent unbroken LOWER
    high (weekly pivot, pivot_w bars each side) formed after B, above max(SMA, entry) and below B ('lh'), if any."""
    h = w["High"].values
    n = len(w)
    b, bi = None, None
    if base_high is not None and base_high > entry:
        lo_i = max(0, n - 105)
        hits = [i for i in range(lo_i, n) if abs(h[i] - base_high) <= max(0.005, base_high * 1e-5)]
        bi = hits[-1] if hits else None
        b = float(base_high)
        if bi is not None and bi < n - 1 and h[bi + 1:].max() > b:
            bi = bi + 1 + int(np.argmax(h[bi + 1:])); b = float(h[bi])
    if b is None or b <= ma_now:
        return {"stop": stop_above(ma_now, R), "basis": "ma", "anchor": ma_now, "b": b, "lh": None}
    stop = stop_above(b, R)
    out = {"stop": stop, "basis": "high", "anchor": b, "b": b, "lh": None}
    ma = w["Close"].rolling(R["ma_weeks"]).mean().values
    sc, _ = slope_class(ma, n - 1, R)
    if (stop - entry) / entry * 100 > R["max_stop_pct"] and sc == "down" and bi is not None:
        lhs = [i for i in pivots(h, R["pivot_w"], True)
               if i > bi and max(ma_now, entry) < h[i] < b and (i == n - 1 or h[i] >= h[i + 1:].max())]
        if lhs:
            hv = float(h[lhs[-1]])
            out.update(stop=stop_above(hv, R), basis="lh", anchor=hv, lh=hv)
    return out


def short_trade_levels(w: pd.DataFrame, ma_now: float, entry: float, support: Optional[float], base_high: Optional[float],
                       R=RULES) -> Dict[str, Any]:
    """Short trade plan: Sell-Stop entry, protective Buy-Stop above higher of (SMA 150 יום, base rally high), target =
    nearest significant support below (last 2 years); none = open sky -> entry - min_rr x risk (if > 0).
    Enforces 0 < target < entry < stop."""
    sa = short_stop_anchors(w, ma_now, entry, base_high, R)
    stop, basis = sa["stop"], sa["basis"]
    swing_high = sa["anchor"] if basis != "ma" else sa["b"]
    sup = support_scan(w, entry, R)
    risk = stop - entry
    target, tsrc = (sup["support"], "support") if sup["support"] else (None, None)
    if target is None and risk > 0:
        t_sky = entry - R["min_rr"] * risk
        if t_sky > 0:
            target, tsrc = t_sky, "open_sky"
    rr = (entry - target) / risk if (target is not None and risk > 0 and 0 < target < entry < stop) else None
    shares = int(R["risk_usd"] // risk) if risk > 0 else None
    stop_pct = risk / entry * 100 if entry else None
    return {"entry": _f(entry), "stop": _f(stop), "stop_basis": basis, "swing_high": _f(swing_high),
            "anchor_b": _f(sa["b"]), "stop_anchor": _f(sa["anchor"]), "target": _f(target), "target_src": tsrc,
            "risk_pct": _f(stop_pct, 1), "stop_wide": bool(stop_pct is not None and stop_pct > R["max_stop_pct"]),
            "rr": _f(rr), "shares": shares, "pos_usd": _f(shares * entry, 0) if shares else None,
            "support": _f(sup["support"]), "support_pct": _f(sup["support_pct"], 1), "open_sky": sup["open_sky"],
            "atl": sup["atl"], "cong": _f(sup["cong"]), "lo2y": _f(sup["lo2y"]),
            "sup_levels": [_f(x) for x in sup["levels"]]}


def earnings_live_week(earn: Optional[str], timing: Optional[str], today: date) -> Tuple[bool, Optional[str], str]:
    """Does the report fall in the week a Buy-Stop placed now would be live? Live week = the Mon-Fri trading week of the
    next session after today (run on Saturday -> next week). An after-close ('a') report counts on the next session."""
    if not earn:
        return False, None, ""
    d = date.fromisoformat(earn)
    if d < today:
        return False, None, ""
    eff = d
    if timing == "a":
        eff = (np.busday_offset(np.datetime64(d), 1, roll="forward")).astype(date)
    nxt = today if today.weekday() < 5 else today + timedelta(days=7 - today.weekday())  # weekend run -> next Monday
    fri = nxt + timedelta(days=4 - nxt.weekday())
    return bool(eff <= fri), eff.isoformat(), fri.isoformat()


def _next_session(d: date) -> date:
    return np.busday_offset(np.datetime64(d), 1, roll="forward").astype(date)


def sessions_until(eff: date, today: date) -> int:
    """Trading sessions from the next one up to and including `eff` (weekends only, no holiday calendar):
    Saturday -> Monday report = 1; a report today (weekday) = 0."""
    return int(np.busday_count(today + timedelta(days=1), eff + timedelta(days=1)))


def earnings_info(fv_date: Optional[str], timing: Optional[str], cache_date: Optional[str], today: date,
                  R=RULES) -> Dict[str, Any]:
    """Next / last report (Eyal 2026-11-14). next = a future FinViz date, else the retest scanner's cached future date,
    else -- FinViz only has a PAST date -- that date + 13 weeks, labelled estimated ('משוער'). eff = the session that
    trades the report (after close -> next session). td = sessions until eff. last = the past FinViz date (if any)."""
    out: Dict[str, Any] = {"next": None, "est": False, "timing": None, "eff": None, "td": None,
                           "last": None, "last_eff": None, "last_ago": None}
    fv = date.fromisoformat(fv_date) if fv_date else None
    if fv and fv < today:
        out["last"] = fv.isoformat()
        le = _next_session(fv) if timing == "a" else fv
        out["last_eff"] = le.isoformat()
        out["last_ago"] = int(np.busday_count(le, today + timedelta(days=1)))  # sessions in [reaction day, today]
    nxt, tm, est = None, None, False
    if fv and fv >= today:
        nxt, tm = fv, timing
    elif cache_date and date.fromisoformat(cache_date) >= today:
        nxt = date.fromisoformat(cache_date)
    elif fv:
        nxt, est = fv, True
        while nxt < today:
            nxt += timedelta(days=R["earn_est_days"])
        nxt = np.busday_offset(np.datetime64(nxt), 0, roll="forward").astype(date)
    if nxt:
        eff = _next_session(nxt) if tm == "a" else nxt
        out.update(next=nxt.isoformat(), est=est, timing=tm, eff=eff.isoformat(), td=sessions_until(eff, today))
    return out


def earn_check(ei: Dict[str, Any], R=RULES, order_label: str = "Buy-Stop") -> Dict[str, Any]:
    """Not in a trade: no new Buy-Stop / Sell-Stop while the report session is within the next earn_td sessions (blocks
    on an estimated date too, labelled). Unknown date -> ok None (can't confirm)."""
    if not ei["next"]:
        return {"k": "earn", "ok": None, "he": f"תאריך הדוח הבא לא ידוע — לבדוק לפני הצבת {order_label}"}
    lab = " (משוער: הדוח האחרון + 13 ש׳)" if ei["est"] else ""
    when = f"{ei['next']}{' אחרי הסגירה' if ei['timing'] == 'a' else ' לפני הפתיחה' if ei['timing'] == 'b' else ''}{lab}"
    if ei["td"] <= R["earn_td"]:
        return {"k": "earn", "ok": False, "he": f"דוח בעוד {ei['td']} ימי מסחר – לא להציב {order_label} (דוח {when})"}
    return {"k": "earn", "ok": True, "he": f"אין דוח ב-{R['earn_td']} ימי המסחר הקרובים (דוח בעוד {ei['td']} ימ״ס: {when})"}


def post_earn_gap(d: Optional[pd.DataFrame], w: pd.DataFrame, last_eff: str, level: float, R=RULES) -> Dict[str, Any]:
    """After a report (Eyal 2026-11-14): gap-up above the resistance on high volume = don't chase; candidate again once
    >= mini_base_d sessions after the gap day all closed above the level (mini-base). Daily candles when available,
    else the weekly close of the report week / later weeks holding above the level."""
    le = pd.Timestamp(last_eff)
    if d is not None and len(d) and (d.index >= le).any() and (d.index < le).any():
        i = int(np.argmax(d.index >= le))
        o, c, vol = float(d["Open"].iloc[i]), float(d["Close"].iloc[i]), float(d["Volume"].iloc[i])
        pc = float(d["Close"].iloc[i - 1])
        av = float(d["Volume"].iloc[max(0, i - R["gap_vol_avg_d"]):i].mean() or 0)
        gap = bool(o >= pc * (1 + R["gap_min_pct"] / 100) and c > level and pc <= level and av > 0 and vol >= R["gap_vol_mult"] * av)
        after = d.iloc[i + 1:]
        hold = bool(gap and len(after) >= R["mini_base_d"] and float(after["Close"].min()) >= level)
        failed = bool(gap and len(after) and float(after["Close"].iloc[-1]) < level)
        return {"src": "daily", "gap": gap, "gap_pct": _f((o / pc - 1) * 100, 1), "vol_x": _f(vol / av, 1) if av else None,
                "days_after": int(len(after)), "hold": hold, "failed": failed,
                "mini_hi": _f(float(after["High"].max())) if len(after) else None,
                "mini_lo": _f(float(after["Low"].min())) if len(after) else None}
    j = int(np.argmax(w.index >= le)) if (w.index >= le).any() else None
    if j is None or j == 0:
        return {"src": "none", "gap": False, "hold": False, "failed": False, "days_after": 0}
    o, c, pc = float(w["Open"].iloc[j]), float(w["Close"].iloc[j]), float(w["Close"].iloc[j - 1])
    gap = bool(o >= pc * (1 + R["gap_min_pct"] / 100) and c > level and pc <= level)
    after = w.iloc[j + 1:]
    return {"src": "weekly", "gap": gap, "gap_pct": _f((o / pc - 1) * 100, 1), "days_after": int(len(after)) * 5,
            "hold": bool(gap and len(after) >= 1 and float(after["Close"].min()) >= level),
            "failed": bool(gap and len(after) and float(after["Close"].iloc[-1]) < level)}


def post_earn_check(ei: Dict[str, Any], pg: Optional[Dict[str, Any]], close: float, level: float, R=RULES) -> Optional[Dict[str, Any]]:
    """Report in the last post_earn_td sessions -> a 'post' check: gap-up not held yet = fail; held / mini-base = pass;
    report passed with the price still just under the resistance = pass ('דוח עבר – להחזיר Buy-Stop')."""
    if ei["last_ago"] is None or ei["last_ago"] > R["post_earn_td"] or pg is None:
        return None
    if pg["gap"]:
        if pg["hold"]:
            return {"k": "post", "ok": True, "he": f"גאפ אחרי דוח ({pg['gap_pct']:+}%) החזיק מעל הרמה ${level:g} ובנה בסיס קטן "
                                                   f"({pg['days_after']} ימים, ${pg.get('mini_lo')}–${pg.get('mini_hi')}) — מועמדת שוב"}
        if pg["failed"]:
            return {"k": "post", "ok": False, "he": f"גאפ אחרי דוח ({pg['gap_pct']:+}%) נכשל — חזרה מתחת לרמה ${level:g}, לא לקנות"}
        return {"k": "post", "ok": False, "he": f"גאפ אחרי דוח – לא לרדוף, להמתין להחזקה/בסיס קטן (גאפ {pg['gap_pct']:+}%"
                                                f"{', מחזור ' + str(pg['vol_x']) + 'x' if pg.get('vol_x') else ''}; {pg['days_after']}/{R['mini_base_d']} ימים מעל ${level:g})"}
    if close < level and (level / close - 1) * 100 <= R["pre_bo_pct"]:
        return {"k": "post", "ok": True, "he": f"דוח עבר ({ei['last']}) – להחזיר Buy-Stop מעל ${level:g}"}
    return {"k": "post", "ok": True, "info": True, "he": f"דוח עבר ({ei['last']}, לפני {ei['last_ago']} ימ״ס) ללא גאפ מעל ההתנגדות"}


def post_earn_gap_down(d: Optional[pd.DataFrame], w: pd.DataFrame, last_eff: str, level: float, R=RULES) -> Dict[str, Any]:
    """Mirror of post_earn_gap for shorts: gap-down below support on high volume = don't chase; wait for >= mini_base_d
    sessions closing below the broken support."""
    le = pd.Timestamp(last_eff)
    if d is not None and len(d) and (d.index >= le).any() and (d.index < le).any():
        i = int(np.argmax(d.index >= le))
        o, c, vol = float(d["Open"].iloc[i]), float(d["Close"].iloc[i]), float(d["Volume"].iloc[i])
        pc = float(d["Close"].iloc[i - 1])
        av = float(d["Volume"].iloc[max(0, i - R["gap_vol_avg_d"]):i].mean() or 0)
        gap = bool(o <= pc * (1 - R["gap_min_pct"] / 100) and c < level and pc >= level and av > 0 and vol >= R["gap_vol_mult"] * av)
        after = d.iloc[i + 1:]
        hold = bool(gap and len(after) >= R["mini_base_d"] and float(after["Close"].max()) <= level)
        failed = bool(gap and len(after) and float(after["Close"].iloc[-1]) > level)
        return {"src": "daily", "gap": gap, "gap_pct": _f((o / pc - 1) * 100, 1), "vol_x": _f(vol / av, 1) if av else None,
                "days_after": int(len(after)), "hold": hold, "failed": failed,
                "mini_hi": _f(float(after["High"].max())) if len(after) else None,
                "mini_lo": _f(float(after["Low"].min())) if len(after) else None}
    j = int(np.argmax(w.index >= le)) if (w.index >= le).any() else None
    if j is None or j == 0:
        return {"src": "none", "gap": False, "hold": False, "failed": False, "days_after": 0}
    o, c, pc = float(w["Open"].iloc[j]), float(w["Close"].iloc[j]), float(w["Close"].iloc[j - 1])
    gap = bool(o <= pc * (1 - R["gap_min_pct"] / 100) and c < level and pc >= level)
    after = w.iloc[j + 1:]
    return {"src": "weekly", "gap": gap, "gap_pct": _f((o / pc - 1) * 100, 1), "days_after": int(len(after)) * 5,
            "hold": bool(gap and len(after) >= 1 and float(after["Close"].max()) <= level),
            "failed": bool(gap and len(after) and float(after["Close"].iloc[-1]) > level)}


def post_earn_short_check(ei: Dict[str, Any], pg: Optional[Dict[str, Any]], close: float, level: float, R=RULES) -> Optional[Dict[str, Any]]:
    if ei["last_ago"] is None or ei["last_ago"] > R["post_earn_td"] or pg is None:
        return None
    if pg["gap"]:
        if pg["hold"]:
            return {"k": "post", "ok": True, "he": f"גאפ מטה אחרי דוח ({pg['gap_pct']:+}%) החזיק מתחת לרמה ${level:g} ובנה בסיס קטן "
                                                   f"({pg['days_after']} ימים, ${pg.get('mini_lo')}–${pg.get('mini_hi')}) — מועמדת שוב לשורט"}
        if pg["failed"]:
            return {"k": "post", "ok": False, "he": f"גאפ מטה אחרי דוח ({pg['gap_pct']:+}%) נכשל — חזרה מעל הרמה ${level:g}, לא לשורט"}
        return {"k": "post", "ok": False, "he": f"גאפ מטה אחרי דוח – לא לרדוף, להמתין להחזקה מתחת לרמה (גאפ {pg['gap_pct']:+}%"
                                                f"{', מחזור ' + str(pg['vol_x']) + 'x' if pg.get('vol_x') else ''}; {pg['days_after']}/{R['mini_base_d']} ימים מתחת ל-${level:g})"}
    if close > level and (close / level - 1) * 100 <= R["pre_bo_pct"]:
        return {"k": "post", "ok": True, "he": f"דוח עבר ({ei['last']}) – להחזיר Sell-Stop מתחת ל-${level:g}"}
    return {"k": "post", "ok": True, "info": True, "he": f"דוח עבר ({ei['last']}, לפני {ei['last_ago']} ימ״ס) ללא גאפ מטה מתחת לתמיכה"}


def sector_status(e: Optional[Dict[str, Any]], R=RULES) -> Dict[str, Any]:
    """Sector / industry ETF gate (Eyal 2026-11-14): never stage 4, and at least one of
    (1) 'שלב 2 מובהק' = stage 2 (broke above its range), close above a RISING SMA 150 יום;
    (2) 'סוף שלב 1 – התעוררות' = close back above the SMA 150 יום and the SMA no longer falling (flat or turning up).
    The sector's Mansfield RS is information only. A stage-3 sector (top / distribution) is neither of the two states
    -> fails unless RULES sector_allow_stage3."""
    if not e:
        return {"ok": None, "case": None, "he": "לא ידוע"}
    above = e["close"] > e["ma30"]
    if e["stage"] == 4:
        return {"ok": False, "case": "4", "he": "שלב 4 – לא"}
    if e["stage"] == 2 and above and e["slope_cls"] == "up":
        return {"ok": True, "case": "2", "he": "שלב 2 מובהק"}
    if e["stage"] == 3 and not R.get("sector_allow_stage3"):
        return {"ok": False, "case": "3", "he": "שלב 3 (פסגה / הפצה) – לא שלב 2 מובהק ולא סוף שלב 1"}
    if above and e["slope_cls"] != "down":
        return {"ok": True, "case": "1late", "he": "סוף שלב 1 – התעוררות" if e["stage"] != 2 else "שלב 2 – מעל ממוצע שטוח (התעוררות)"}
    why = "מתחת ל-SMA 150 יום" if not above else "ה-SMA 150 יום עדיין יורד"
    return {"ok": False, "case": "no", "he": f"לא עומד: {why}"}


def short_sector_status(e: Optional[Dict[str, Any]], R=RULES) -> Dict[str, Any]:
    """Short-side sector / industry ETF gate: stage 3 or 4, never stage 1 or clear stage 2 (2-weak also fails while
    SMA 150 יום is still rising). Stage 4 below SMA passes; stage 3 passes when below SMA or SMA not rising."""
    if not e:
        return {"ok": None, "case": None, "he": "לא ידוע"}
    above = e["close"] > e["ma30"]
    if e["stage"] == 2:
        msg = "שלב 2 (2-weak, הממוצע עדיין עולה) – לא לשורט" if e.get("sub") == "2-weak" else "שלב 2 – לא לשורט"
        return {"ok": False, "case": "2", "he": msg}
    if e["stage"] == 1:
        return {"ok": False, "case": "1", "he": "שלב 1 (בסיס) – לא בשלב 3 או 4"}
    if e["stage"] == 4 and not above and e["slope_cls"] == "down":
        return {"ok": True, "case": "4", "he": "שלב 4 מובהק"}
    if e["stage"] == 4 and not above:
        return {"ok": True, "case": "4", "he": "שלב 4 (מתחת לממוצע)"}
    if e["stage"] == 3 and (not above or e["slope_cls"] != "up"):
        return {"ok": True, "case": "3", "he": "שלב 3 (פסגה / הפצה)"}
    why = "מעל SMA 150 יום" if above else "ה-SMA 150 יום עדיין עולה"
    return {"ok": False, "case": "no", "he": f"לא עומד לשורט: {why}"}


def etf_gate(industry: Optional[str], sector: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(industry ETF or None, SPDR sector ETF or None, the ETF that GATES the stock).
    Eyal 2026-11-16: industry ETF when the FinViz industry maps, else the broad sector."""
    ind = INDUSTRY_ETF.get(industry or "")
    sec = SECTOR_ETF.get(sector or "")
    return ind, sec, ind or sec


def weekly_atr(w: pd.DataFrame, n: int = 14) -> Optional[float]:
    """Wilder ATR(14) of weekly bars — same formula as webapp/src/data.ts atr()."""
    if w is None or len(w) < n + 1 or not {"High", "Low", "Close"} <= set(w.columns):
        return None
    h, l, c = (w[k].astype(float) for k in ("High", "Low", "Close"))
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1).iloc[1:]
    a = float(tr.iloc[:n].mean())
    for x in tr.iloc[n:]:
        a = (a * (n - 1) + float(x)) / n
    return a


def entry_pass(entry: List[Dict[str, Any]], pre: List[Dict[str, Any]]) -> bool:
    """All entry gates True (an 'info' check, e.g. a wide SL, never disqualifies) and no pre-filter failure."""
    return bool(entry) and all(x["ok"] is True for x in entry if not x.get("info")) and all(x["ok"] is not False for x in pre)


def trading_days_until(d: Optional[str], today: date) -> Optional[int]:
    if not d:
        return None
    dd = date.fromisoformat(d)
    if dd < today:
        return None
    return int(np.busday_count(today, dd))


def _range(h: np.ndarray, l: np.ndarray, i: int, start: int, st: int, R=RULES) -> Tuple[float, float]:
    """Trading range of a base / top (stage 1 / 3) before week i: highest high + lowest low since the range began =
    the earliest of the stage start, min_base_w weeks back and the extreme that ended the prior trend (the lowest low of
    the last range_max_w weeks for a base, the highest high for a top); at most range_max_w weeks back."""
    a0 = max(0, i - R["range_max_w"])
    ext = a0 + int(np.argmin(l[a0:i]) if st == 1 else np.argmax(h[a0:i]))
    a = max(a0, min(start, i - R["min_base_w"], ext))
    return float(h[a:i].max()), float(l[a:i].min())


def _trend_edge(h: np.ndarray, l: np.ndarray, i: int, up: bool, R=RULES) -> float:
    """Stage 2: floor of the current continuation base = lowest low since the last 26-week high (>= min_base_w weeks).
    Stage 4: ceiling = highest high since the last 26-week low."""
    a0 = max(0, i - R["base_window_w"])
    if up:
        k = a0 + int(np.argmax(h[a0:i]))
        return float(l[max(0, min(k, i - R["min_base_w"])):i].min())
    k = a0 + int(np.argmin(l[a0:i]))
    return float(h[max(0, min(k, i - R["min_base_w"])):i].max())



def _weekly_atr_aligned(daily: pd.DataFrame, n: int = 14) -> np.ndarray:
    """Wilder ATR of Friday weeks, forward-filled onto each daily bar.

    'Near' and 'far below' stay 1 weekly ATR (Eyal t453u) even though the stage
    path itself runs on daily bars.
    """
    if daily is None or getattr(daily, "empty", True):
        return np.full(0, np.nan)
    d = daily
    last = pd.Timestamp(d.index.max()).normalize()
    wk = weekly(d, last)
    if wk is None or len(wk) == 0:
        return np.full(len(d), np.nan)
    wa = _wilder_atr(
        wk["High"].values.astype(float),
        wk["Low"].values.astype(float),
        wk["Close"].values.astype(float),
        n,
    )
    s = pd.Series(wa, index=pd.to_datetime(wk.index))
    aligned = s.reindex(pd.to_datetime(d.index), method="ffill")
    # days after the last completed Friday keep the last weekly ATR
    aligned = aligned.ffill().bfill()
    return aligned.values


def stage_path(w: pd.DataFrame, ma: np.ndarray, R=None) -> Dict[str, Any]:
    """Weekly Weinstein / TraderLion stage state machine (Eyal 2026-11-27).

    All tests are on completed weekly (W-FRI) bars, the 30-week SMA (≈150-day) and
    the 10-week SMA (≈50-day).

    Stage 1 (base): after stage 4, the SMA 150 יום has flattened / stopped declining,
    and price moves sideways, whipsawing around the MA. If the MA is still sloping
    sharply down and price is far below it (more than 1 weekly ATR), it stays 4.

    Stage 2a (breakout, Ideal Buy point A): a weekly close above the stage-1 base
    ceiling on volume >= 2x the prior 10-week average, with the SMA 150 יום not
    declining and the close above it. Stays 2a for the breakout week plus
    stage_2a_weeks (6) further weeks while price is still within 2 weekly ATRs of
    the breakout, including the first light-volume (< 1.5x) retest of the ceiling
    that holds (close not more than 0.5 ATR under the level — point B).

    Stage 2 / 2b: after 2a. Price above a rising SMA 150 יום with higher highs / higher
    lows. A light-volume retest that holds at or slightly above the breakout stays 2.
    A weekly close below the SMA 150 יום is no longer stage 2 (the old 2-dip / 2-weak
    rule is removed): go to 4 if the last higher low / stage-3 support is also
    broken, otherwise to 3.

    Stage 3 (distribution): the SMA 150 יום flattens and price chops around it, often
    with heavy-volume churn, failed new highs, or an early warning close below the
    10W SMA on heavy volume (>= 2x).

    Stage 4: a close below stage-3 support, or below the last higher low of the
    stage-2 advance, starts stage 4 EVEN IF the SMA 150 יום is still flat. Then lower
    highs / lower lows, price below the MA, and the MA starts declining. Weak
    light-volume rallies do not change it. 4→1 only after the MA has actually
    declined during this stage-4 run and then flattened, with price no longer far
    below it.
    """
    if R is None:
        R = RULES
    R = _stage_R(R)
    h, l, c, v = (w[k].values.astype(float) for k in ("High", "Low", "Close", "Volume"))
    n = len(w)
    ma10_w = int(R.get("sma10_weeks", 10))
    ma10 = w["Close"].rolling(ma10_w).mean().values
    atr = _weekly_atr_aligned(w, 14)
    avg_w = int(R.get("vol_avg_w", 10))
    vol_mult = float(R.get("vol_mult", 2.0))
    light_vol = float(R.get("light_vol_mult", 1.5))
    a2_weeks = int(R.get("stage_2a_weeks", 6))
    a2_near = float(R.get("stage_2a_near_atrs", 2.0))
    hold_atrs = float(R.get("retest_hold_atrs", 0.5))
    k_pv = int(R.get("pivot_w", 2))
    pl_all = pivots(l, k_pv, False)

    i0 = int(R["ma_weeks"]) + int(R.get("sma_slope_w", 3)) - 1
    st, sub, start = None, None, i0
    bo_level, bo_i, bo_vol = None, None, None
    adv_hl = None      # last confirmed swing low of the advance (not the ceiling)
    base_floor = None  # stage-1 floor, last-resort support of the advance
    saw_down = False   # SMA 150d was 'down' at least once in the current stage-4 run
    run_2_start = None # start of the most recent stage-2 run (last_hl origin after 2→3)

    def slope_at(i):
        return sma_slope(ma, i, R)

    def far(i):
        return _far_below(c[i], ma[i], atr[i], R)

    def vr(i):
        return _week_vol_ratio(v, i, avg_w)

    def heavy(i):
        r = vr(i)
        return r is not None and r >= vol_mult

    def light(i):
        r = vr(i)
        return r is not None and r < light_vol

    def last_hl(i):
        """Last confirmed swing low of the current advance, else the base floor.

        Origin is the most recent stage-2 start, not the current stage start, so a
        fresh stage-3 box does not throw away the last higher low of the advance.
        """
        origin = run_2_start if run_2_start is not None else start
        confirmed = [j for j in pl_all if j + k_pv <= i and (origin is None or j >= origin)]
        if confirmed:
            return float(l[confirmed[-1]])
        return adv_hl if adv_hl is not None else base_floor

    def cons_above(i, need=None, window=None):
        need = int(R.get("idx_consistent_n", 20) if need is None else need)
        window = int(R.get("idx_consistent_w", 25) if window is None else window)
        a0 = max(int(R["ma_weeks"]) - 1, i - window + 1)
        return int(np.sum(c[a0:i + 1] > ma[a0:i + 1])) >= need

    for i in range(i0, n):
        sc, _, sharp = slope_at(i)
        if sc is None or np.isnan(ma[i]):
            continue
        above = bool(c[i] > ma[i])
        a = atr[i]
        if st is None:
            if sc == "down" or (sc == "flat" and far(i)):
                st, sub, start = 4, "4", i
                saw_down = sc == "down" or sharp
            elif sc == "up" and above:
                st, sub, start = 2, "2", i
            elif sc == "flat" and above:
                st, sub, start = 3, "3", i
            else:
                st, sub, start = 1, "1", i
            continue

        new, new_sub = st, sub

        if st == 4:
            if sc == "down" or sharp:
                saw_down = True
            # Failed breakdown: back above broken support and back above the SMA 150 יום
            # Recover only back above the last HL of the advance, not the ancient
            # stage-1 floor (that recovery was almost always true and caused 2↔4 flips).
            rec_lvl = adv_hl if adv_hl is not None else base_floor
            # Back above a rising 150d is stage 2 again (the inverse of "a close
            # below the MA exits stage 2"), even if the last HL has not been reclaimed.
            if above and sc == "up":
                new, new_sub = 2, "2"
            elif above and rec_lvl is not None and c[i] > rec_lvl and sc != "down":
                new, new_sub = (2, "2") if sc == "up" else (3, "3")
            elif saw_down and sc == "flat" and not sharp and not far(i) and (
                above or (a is not None and not np.isnan(a) and a > 0 and abs(c[i] - ma[i]) <= a)
            ):
                new, new_sub = 1, "1"

        elif st == 1:
            ceil, floor = _range(h, l, i, start, 1, R)
            if c[i] > ceil and sc != "down" and above and heavy(i):
                new, new_sub = 2, "2a"
                bo_level, bo_i, bo_vol = float(ceil), i, vr(i)
                base_floor = float(floor) if floor is not None else base_floor
                adv_hl = base_floor
            elif sc == "up" and above and (c[i] > ceil or cons_above(i)):
                new, new_sub = 2, "2"
                base_floor = float(floor) if floor is not None else base_floor
                if c[i] > ceil and bo_level is None:
                    bo_level, bo_i = float(ceil), i
                if adv_hl is None:
                    adv_hl = base_floor
            elif far(i) or (floor is not None and c[i] < floor and sc != "up") or (sc == "down" and (sharp or far(i))):
                new, new_sub = 4, "4"
                base_floor = float(floor) if floor is not None else base_floor
                saw_down = sc == "down" or sharp or far(i)

        elif st == 2:
            floor_2 = last_hl(i)
            broke_hl = floor_2 is not None and c[i] < floor_2

            if sub == "2a" and bo_level is not None and bo_i is not None:
                weeks_since = i - bo_i
                near_bo = abs(c[i] - bo_level) <= _atr_or_pct(bo_level, a, a2_near)
                held_retest = (
                    light(i)
                    and c[i] >= bo_level - _atr_or_pct(bo_level, a, hold_atrs)
                    and (c[i] - bo_level) <= _atr_or_pct(bo_level, a, a2_near)
                )
                failed_bo = c[i] < bo_level - _atr_or_pct(bo_level, a, 1.0)
                if broke_hl and not (above and sc == "up"):
                    new, new_sub = 4, "4"
                    saw_down = sc == "down" or sharp
                elif failed_bo or not above:
                    # failed / rejected breakout — back to the base if the floor holds
                    if broke_hl:
                        new, new_sub = 4, "4"
                        saw_down = sc == "down" or sharp
                    else:
                        new, new_sub = (3, "3") if not above and not failed_bo else (1, "1")
                elif weeks_since > a2_weeks and not held_retest:
                    new, new_sub = 2, "2"
                elif (not near_bo) and c[i] > bo_level + _atr_or_pct(bo_level, a, a2_near) and not held_retest:
                    new, new_sub = 2, "2"
                else:
                    new, new_sub = 2, "2a"
            else:
                # A taken-out pullback low is not stage 4 while price is still above
                # a rising 150d. Stage 4 on a support break applies when the MA is
                # flat or down, or when price has already lost the MA (Eyal: even if
                # the MA is still flat). 
                if (broke_hl or (not above and far(i))) and not (above and sc == "up"):
                    new, new_sub = 4, "4"
                    saw_down = sc == "down" or sharp or far(i)
                elif not above:
                    new, new_sub = 3, "3"
                elif sc == "flat":
                    below_10 = (not np.isnan(ma10[i])) and c[i] < ma10[i] and heavy(i)
                    a0 = max(0, i - int(R.get("base_window_w", 26)))
                    since_hi = i - (a0 + int(np.argmax(h[a0:i + 1])))
                    if below_10 or since_hi >= int(R.get("idx_top_w", 10)):
                        new, new_sub = 3, "3"

        elif st == 3:
            ceil, floor = _range(h, l, i, start, 3, R)
            # Remember the tighter of stage-3 range floor and the last HL of the advance
            brk_lvl = floor
            hl = last_hl(i) if adv_hl is not None or base_floor is not None else adv_hl
            # Stage 3 support should be the range floor of the top, but don't use a
            # 1-week-old box whose floor is just last week's low — require the box
            # to include the last HL or at least min_base_w weeks when possible.
            if hl is not None and (brk_lvl is None or hl < brk_lvl):
                # last HL of the advance is a valid 4-trigger; the fresh box floor
                # of a 1-2 week top is too tight, so only use it after min_base_w
                if (i - start) >= int(R.get("min_base_w", 10)):
                    pass  # brk_lvl stays the box floor
                else:
                    brk_lvl = hl
            brk = brk_lvl is not None and c[i] < brk_lvl
            # Distribution that has clearly rolled into a decline: below a declining
            # SMA 150 יום, especially when far below it, is stage 4 (TraderLion).
            # Support break, or price already far below the 150d (1 weekly ATR), even
            # if the MA has not turned down yet (Eyal: stage 4 does not wait for the MA).
            rolled = (not above) and (far(i) or sc == "down" or sharp)
            if brk or rolled:
                new, new_sub = 4, "4"
                saw_down = sc == "down" or sharp or far(i)
                if base_floor is None:
                    base_floor = brk_lvl
            elif c[i] > ceil and sc != "down" and above and heavy(i):
                new, new_sub = 2, "2a"
                bo_level, bo_i, bo_vol = float(ceil), i, vr(i)
            elif sc == "up" and above and (c[i] > ceil or cons_above(i)):
                new, new_sub = 2, "2"
                if c[i] > ceil and bo_level is None:
                    bo_level, bo_i = float(ceil), i

        if new != st or new_sub != sub:
            if new != st:
                start = i
                if new == 1:
                    bo_level = bo_i = bo_vol = None
                    run_2_start = None
                if new == 2 and st != 2:
                    run_2_start = i
                if new != 4:
                    saw_down = False
                if new == 4 and base_floor is None:
                    base_floor = last_hl(i)
            st, sub = new, new_sub
            if st == 2:
                hl_now = last_hl(i)
                if hl_now is not None:
                    adv_hl = hl_now
                elif adv_hl is None:
                    adv_hl = base_floor
        elif st == 2:
            hl_now = last_hl(i)
            if hl_now is not None:
                adv_hl = hl_now

    i = n - 1
    sc, sl, sharp = slope_at(i) if i >= 0 else (None, None, False)
    if st in (1, 3):
        ceil, floor = _range(h, l, i + 1, start, st, R)
    elif st == 2:
        ceil = float(h[max(0, (bo_i if bo_i is not None else start)):].max()) if n else None
        floor = last_hl(i)
    else:
        ceil = _trend_edge(h, l, i + 1, False, R)
        floor = float(l[max(0, i + 1 - int(R["base_window_w"])):].min()) if n else None
    return {
        "stage": st, "sub": sub or (str(st) if st else None),
        "start": start, "since_w": n - 1 - start if st is not None else 0,
        "ceil": ceil, "floor": floor,
        "bo_level": bo_level, "bo_i": bo_i, "bo_vol": bo_vol,
        "adv_hl": last_hl(i) if st in (2, 3, 4) else adv_hl,
        "base_floor": base_floor,
        "slope_cls": sc, "slope": sl, "sharp_down": sharp,
        "ma10": None if i < 0 or np.isnan(ma10[i]) else float(ma10[i]),
        "vol_ratio": vr(i) if i >= 0 else None,
        "atr": None if i < 0 or np.isnan(atr[i]) else float(atr[i]),
    }


def classify(daily: pd.DataFrame, bench_w: Optional[pd.Series], R=RULES) -> Optional[Dict[str, Any]]:
    """Daily Weinstein / TraderLion stage (150d and 50d SMA) plus weekly Buy-Stop / RS helpers.

    Eyal 2026-11-27 (t453u): breakouts, breakdowns and the stage path use daily closes and
    the 150-day SMA. find_breakout, Mansfield RS and weekly ATR stay on completed Friday
    weeks so Buy-Stop entries, Stef stops and R:R are unchanged.
    """
    if daily is None or getattr(daily, "empty", True):
        return None
    d = daily.copy()
    d.index = pd.to_datetime(d.index)
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    last = pd.Timestamp(d.index.max()).normalize()
    wk = weekly(d, last)
    SR = _stage_R(R)
    n = len(d)
    if n < SR["ma_weeks"] + SR["sma_slope_w"]:
        return None
    w = d
    c, h, l, v = (w[k].values.astype(float) for k in ("Close", "High", "Low", "Volume"))
    ma = w["Close"].rolling(SR["ma_weeks"]).mean().values
    i = n - 1
    sc, slope, _sharp = sma_slope(ma, i, SR)
    above = c[i] > ma[i]
    # Mansfield RS stays weekly (a 52-week relative-strength measure).
    if bench_w is not None and wk is not None and len(wk):
        rs_s = mansfield(wk["Close"], bench_w, R)
        rs_now = float(rs_s.iloc[-1]) if len(rs_s) else float("nan")
        prev_i = len(rs_s) - 1 - R["rs_rising_w"]
        rs_prev = float(rs_s.iloc[prev_i]) if prev_i >= 0 else float("nan")
    else:
        rs_now = rs_prev = float("nan")
    rs_up = bool(rs_now > rs_prev) if not (np.isnan(rs_now) or np.isnan(rs_prev)) else None
    k = SR["pivot_w"]
    ph = [j for j in pivots(h, k, True) if j >= n - 260]
    pl = [j for j in pivots(l, k, False) if j >= n - 260]
    hh = bool(h[ph[-1]] > h[ph[-2]]) if len(ph) >= 2 else None
    hl = bool(l[pl[-1]] > l[pl[-2]]) if len(pl) >= 2 else None
    # prior trend for a flat MA (150d slope over the last year of sessions)
    prior = None
    for j in range(i - 1, max(SR["ma_weeks"] + SR["sma_slope_w"] - 2, i - SR["prior_trend_w"]), -1):
        s2, _, _ = sma_slope(ma, j, SR)
        if s2 in ("up", "down"):
            prior = s2
            break
    hi52, lo52 = h[-252:].max(), l[-252:].min()
    if prior is None:
        prior = "down" if c[i] < (hi52 + lo52) / 2 else "up"
    flat_run = 0
    for j in range(i, -1, -1):
        s2, _, _ = sma_slope(ma, j, SR)
        if s2 == "flat":
            flat_run += 1
        else:
            break
    crosses13 = int(np.sum(np.diff(np.sign(c[-31:] - ma[-31:])) != 0))  # ~6 weeks of sessions
    vol10, vol52 = v[-50:].mean(), v[-252:].mean()
    new_high_10 = bool(h[-50:].max() >= hi52)
    ma_w = wk["Close"].rolling(R["ma_weeks"]).mean().values if wk is not None and len(wk) >= R["ma_weeks"] else None
    bo = find_breakout(wk, ma_w, R) if ma_w is not None else None
    bo_ok = None
    if bo:
        bo["holding"] = bool(c[i] >= bo["level"] and above)
        bo["vol_ok"] = bool(bo["vol_ratio"] is not None and bo["vol_ratio"] >= R["vol_mult"])
        bo["pct_above"] = _f((c[i] / bo["level"] - 1) * 100, 1)
        bo_ok = bo["holding"] and bo["vol_ok"]
    bd = find_breakdown(wk, ma_w, R) if ma_w is not None else None
    bd_ok = None
    if bd:
        bd["holding"] = bool(c[i] <= bd["level"] and not above)
        bd["vol_ok"] = bool(bd["vol_ratio"] is not None and bd["vol_ratio"] >= R["vol_mult"])
        bd["pct_below"] = _f((1 - c[i] / bd["level"]) * 100, 1)
        bd_ok = bd["holding"]  # Weinstein: breakdown volume is nice, not required for shorts

    sp = stage_path(w, ma, R)
    stage = sp["stage"] or (2 if sc == "up" else 4 if sc == "down" else 1 if prior == "down" else 3)
    if bo_ok and stage != 2:
        bo_ok = False  # broke a 26-week high but is still inside the bigger base range -> not a stage-2 breakout yet
        bo["in_range"] = True
    if bd_ok and stage != 4:
        bd_ok = False  # broke a 26-week low but is still inside the bigger stage-3 range -> not stage 4 yet
        bd["in_range"] = True
    if stage == 2:
        sub = sp.get("sub") or "2"
        if sub not in ("2a", "2A") and (c[i] / ma[i] - 1) * 100 > R["extended_pct"]:
            sub = "2-ext"
    elif stage == 4:
        sub = "4A" if bd_ok else ("4-ext" if (1 - c[i] / ma[i]) * 100 > R["extended_pct"] else "4" if not above else "4-late")
    elif stage == 1:
        sub = "1B" if sp["since_w"] >= SR["min_base_w"] else "1A"
    else:
        sub = "3"
    def ck(key, ok, he):
        return {"k": key, "ok": None if ok is None else bool(ok), "he": he}
    checks = {
        1: [ck("ma_flat", sc == "flat", f"SMA 150 יום שטוח (שינוי ≤{SR['sma_slope_flat_pct']}% ב-{SR['sma_slope_w']} ימי מסחר)"),
            ck("base10", flat_run >= SR["min_base_w"], f"בסיס בוגר: ממוצע שטוח {flat_run} ימים (≥{SR['min_base_w']})"),
            ck("cross", crosses13 >= 1, f"המחיר חוצה את הממוצע הלוך ושוב ({crosses13} חציות ב-30 ימי מסחר)"),
            ck("dry", vol10 < vol52, "מחזור מתייבש: ממוצע 50 יום < ממוצע 252 יום")],
        2: [ck("above", above, "סגירה יומית מעל SMA 150 יום"),
            ck("ma_up", sc == "up" or (bo_ok and sc == "flat"), "SMA 150 יום עולה (בפריצה: שטוח-עולה)"),
            ck("hhhl", (hh and hl) if hh is not None and hl is not None else None, "שיאים עולים ושפלים עולים (שנה)"),
            ck("rs", (rs_now > 0 and rs_up) if rs_up is not None else None, "Mansfield RS > 0 ועולה (שבועי)")],
        3: [ck("ma_flat", sc == "flat", "SMA 150 יום שטוח אחרי עלייה"),
            ck("whipsaw", crosses13 >= 2, f"חציות של הממוצע הלוך ושוב ({crosses13} ב-30 ימים, ≥2)"),
            ck("churn", vol10 > vol52 and not new_high_10, "מחזור גבוה (50י > 252י) בלי שיא שנתי חדש"),
            ck("rs_weak", (not rs_up) if rs_up is not None else None, "Mansfield RS נחלש (יורד ב-4 שבועות)")],
        4: [ck("below", not above, "סגירה יומית מתחת ל-SMA 150 יום"),
            ck("ma_down", sc == "down", f"SMA 150 יום יורד (או נשברה תמיכה; שיפוע {SR['sma_slope_w']} ימים)"),
            ck("lhll", ((hh is False) and (hl is False)) if hh is not None and hl is not None else None, "שיאים יורדים ושפלים יורדים"),
            ck("rs_neg", (rs_now < 0 and rs_up is False) if rs_up is not None else None, "Mansfield RS < 0 ויורד")],
    }[stage]
    score = sum(1 for x in checks if x["ok"])
    out = {
        "stage": stage, "sub": sub, "score": score, "conf": "high" if score == 4 else "med" if score == 3 else "low",
        "checks": checks, "week": w.index[i].strftime("%Y-%m-%d"), "close": _f(c[i]), "ma30": _f(ma[i]),
        "ma150": _f(ma[i]), "ma50": _f(sp.get("ma10")),
        "slope": _f(slope), "slope_cls": sc, "pct_ma": _f((c[i] / ma[i] - 1) * 100, 1), "rs": _f(rs_now, 1),
        "rs_prev": _f(rs_prev, 1), "rs_up": rs_up, "hh": hh, "hl": hl, "prior": prior, "flat_w": flat_run,
        "crosses13": crosses13, "hi52": _f(hi52), "pct_hi52": _f((c[i] / hi52 - 1) * 100, 1),
        "at_hi52": bool(c[i] >= hi52 * 0.97), "weeks": len(wk) if wk is not None else n, "days": n,
        "tf": "daily", "ma_kind": "150d", "bo": None, "bd": None,
        "range": {"ceil": _f(sp["ceil"]), "floor": _f(sp["floor"]), "since_w": sp["since_w"],
                  "since_d": sp["since_w"],
                  "since": w.index[sp["start"]].strftime("%Y-%m-%d") if sp["stage"] else None},
    }
    if bo:
        out["bo"] = {k2: (_f(v2) if isinstance(v2, float) else v2) for k2, v2 in bo.items() if k2 != "idx"}
    elif sp.get("bo_level"):
        out["bo"] = {"level": _f(sp["bo_level"]), "vol_ratio": _f(sp.get("bo_vol"), 2),
                     "vol_ok": bool(sp.get("bo_vol") and sp["bo_vol"] >= R["vol_mult"])}
    out["ma10"] = _f(sp.get("ma10"))
    out["vol_ratio"] = _f(sp.get("vol_ratio"), 2)
    # trade plan (Eyal 2026-11-14): the entry is ALWAYS a Buy-Stop slightly above the base resistance -- 2A = that level
    # just broke (buy only while still in the buy zone, else don't chase); stage 1 / stage-2 continuation base = the order
    # waits above the ceiling. R:R from that Buy-Stop entry to the nearest overhead resistance (2 years).
    out["pct_above_ma_lim"] = bool((c[i] / ma[i] - 1) * 100 > R["max_pct_above_ma"])
    if bo_ok:
        p = trade_levels(w, ma[i], buy_stop_price(bo["level"], R), bo["level"], bo.get("stop_low", bo["base_low"]), R)
        p["kind"] = "breakout"
        out["plan"] = p
    else:
        bn = None
        if stage == 1:  # Buy-Stop above the ceiling of the stage-1 trading range
            bn = {"top": sp["ceil"], "low": sp["floor"], "weeks": sp["since_w"], "since_top_w": sp["since_w"],
                  "top_week": out["range"]["since"], "mature": bool(sp["since_w"] >= R["min_base_w"])}
        elif stage == 2 and sub != "2-ext" and sc != "down":  # continuation base inside stage 2
            bn = base_now(w, R)
            if bn and not bn["mature"]:
                bn = None
        if bn:
            out["base"] = {"top": _f(bn["top"]), "low": _f(bn["low"]), "weeks": bn["weeks"], "since_top_w": bn["since_top_w"],
                           "top_week": bn["top_week"], "mature": bn["mature"], "dist_pct": _f((bn["top"] / c[i] - 1) * 100, 1)}
            p = trade_levels(w, ma[i], buy_stop_price(bn["top"], R), bn["top"], bn.get("stop_low", bn["low"]), R)
            p["kind"] = "trigger" if stage == 1 else "continuation"
            av = float(v[-R["vol_avg_w"]:].mean())
            p["vol_need"] = _f(av * R["vol_mult"], 0)
            out["plan"] = p
    if out.get("plan"):
        p = out["plan"]
        lvl = bo["level"] if bo_ok else out["base"]["top"]
        p["level"] = _f(lvl)
        p["close_vs_level"] = _f((c[i] / lvl - 1) * 100, 1)
        p["entry_vs_ma"] = _f((p["entry"] / ma[i] - 1) * 100, 1)
        # don't chase: price (or the Buy-Stop) too far above the breakout level / the SMA 150 יום
        far = max(c[i], p["entry"])
        p["chase"] = bool((far / lvl - 1) * 100 > R["buy_zone_pct"] or (far / ma[i] - 1) * 100 > R["max_pct_above_ma"])
    # short trade plan (mirror): Sell-Stop slightly below base support -- 4A = fresh breakdown; stage 3 / stage 4
    # continuation base = order waits below the floor.
    if bd:
        out["bd"] = {k2: (_f(v2) if isinstance(v2, float) else v2) for k2, v2 in bd.items() if k2 != "idx"}
    if bd_ok:
        sp_s = short_trade_levels(w, ma[i], sell_stop_price(bd["level"], R), bd["level"], bd.get("stop_high", bd["base_high"]), R)
        sp_s["kind"] = "breakdown"
        out["short_plan"] = sp_s
    else:
        sbn = None
        if stage == 3:
            sbn = {"floor": sp["floor"], "top": sp["ceil"], "weeks": sp["since_w"], "since_bot_w": sp["since_w"],
                   "bot_week": out["range"]["since"], "mature": bool(sp["since_w"] >= R["min_base_w"])}
        elif stage == 4 and sub != "4-ext" and sc != "up":
            sbn = short_base_now(w, R)
            if sbn and not sbn["mature"]:
                sbn = None
        if sbn:
            out["short_base"] = {"floor": _f(sbn["floor"]), "top": _f(sbn["top"]), "weeks": sbn["weeks"],
                                 "since_bot_w": sbn["since_bot_w"], "bot_week": sbn["bot_week"],
                                 "mature": sbn["mature"], "dist_pct": _f((c[i] / sbn["floor"] - 1) * 100, 1)}
            sp_s = short_trade_levels(w, ma[i], sell_stop_price(sbn["floor"], R), sbn["floor"], sbn.get("stop_high", sbn["top"]), R)
            sp_s["kind"] = "trigger" if stage == 3 else "continuation"
            out["short_plan"] = sp_s
    if out.get("short_plan"):
        p = out["short_plan"]
        lvl = bd["level"] if bd_ok else out["short_base"]["floor"]
        p["level"] = _f(lvl)
        p["close_vs_level"] = _f((c[i] / lvl - 1) * 100, 1)
        p["entry_vs_ma"] = _f((p["entry"] / ma[i] - 1) * 100, 1)
        far = min(c[i], p["entry"])
        p["chase"] = bool((1 - far / lvl) * 100 > R["sell_zone_pct"] or (1 - far / ma[i]) * 100 > R["max_pct_below_ma"])
    return out


# ----------------------------------------------------------------------------------------------- index / sector ETF stage
# Eyal 2026-11-15: an index (SPY / QQQ) or sector ETF is classified on its own 4 objective parameters (weekly chart,
# SMA 150 יום): (1) price vs the SMA (consistently above / below, or crossing back and forth), (2) the SMA slope,
# (3) the swing structure (HH/HL vs LH/LL) with the range support / resistance, (4) the practical (top-down) meaning.
# Rule 1: slope beats a single cross -- stage 4 needs a FALLING SMA AND a close below significant support (the last
# confirmed swing low / the range floor); a dip under a rising SMA that keeps its higher low stays stage 2.
# Rule 2: back above a SMA 150 יום that went flat after a decline = late stage 1 / turning point ('1T').
# Rule 3: top-down -- market stage 3 / 4 = no new long Buy-Stops; market 2 + sector 2 = full allocation; sector 4 = avoid.
IDX_TD = {  # top-down meaning (Eyal's table, 'משמעות מעשית למסחר')
    1: ("caution", "המתנה / זהירות — מותר לסמן מובילות שפורצות מוקדם"),
    "1T": ("turn", "נקודת מפנה (סוף שלב 1) — מותר לקנות את המובילות שעומדות לפרוץ"),
    2: ("full", "אור ירוק מלא — פריצות של מניות חזקות"),
    3: ("defend", "הגנה וצמצום חשיפה — אין לונג חדש, להדק סטופים"),
    4: ("avoid", "אור אדום ללונג — לא קונים מניות חדשות"),
    "2a": ("full", "פריצה (2a) — נקודת הקנייה האידיאלית, מחזור ≥2x"),
    "2-dip": ("full", "שלב 2"),
    "2-weak": ("caution", "שלב 2"),
}


def _swings(h: np.ndarray, l: np.ndarray, i: int, k: int, ph: List[int], pl: List[int]) -> Tuple[List[int], List[int]]:
    """Swing highs / lows confirmed by week i (a pivot j needs k bars after it: j + k <= i)."""
    return [j for j in ph if j + k <= i], [j for j in pl if j + k <= i]


def classify_index(daily: pd.DataFrame, bench_w: Optional[pd.Series] = None, R=RULES) -> Optional[Dict[str, Any]]:
    """Weinstein / TraderLion stage of an index or sector ETF on daily bars (Eyal 2026-11-27, t453u).

    Daily closes, 150-day SMA and 50-day SMA; slope is the 20-session percent change of the 150d SMA.
    Market / sector gates follow this classifier, so they switch to the daily engine with it.
    Mansfield RS stays on weekly closes.
    """
    if daily is None or getattr(daily, "empty", True):
        return None
    d = daily.copy()
    d.index = pd.to_datetime(d.index)
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    last = pd.Timestamp(d.index.max()).normalize()
    wk = weekly(d, last)
    SR = _stage_R(R)
    w = d
    n = len(w)
    if n < SR["ma_weeks"] + SR["sma_slope_w"]:
        return None
    h, l, c = (w[k].values.astype(float) for k in ("High", "Low", "Close"))
    ma = w["Close"].rolling(SR["ma_weeks"]).mean().values
    k = SR["idx_pivot_w"]
    PH, PL = pivots(h, k, True), pivots(l, k, False)
    cw, cn = SR["idx_consistent_w"], SR["idx_consistent_n"]

    def above_n(i: int) -> int:
        a = max(R["ma_weeks"] - 1, i - cw + 1)
        return int(np.sum(c[a:i + 1] > ma[a:i + 1]))

    def struct(i: int) -> Tuple[Optional[bool], Optional[bool], List[int], List[int]]:
        ph, pl = _swings(h, l, i, k, PH, PL)
        hh = bool(h[ph[-1]] > h[ph[-2]]) if len(ph) >= 2 else None
        hl = bool(l[pl[-1]] > l[pl[-2]]) if len(pl) >= 2 else None
        # structure in progress: a close above the last swing high = a new higher high being made; a close below the
        # last swing low = the higher low is gone (a lower low)
        if ph and c[i] > h[ph[-1]]:
            hh = True
        if pl and c[i] < l[pl[-1]]:
            hl = False
        return hh, hl, ph, pl

    i = n - 1
    sp = stage_path(w, ma, R)
    st = sp["stage"] or (2 if (sma_slope(ma, i, SR)[0] == "up") else 4)
    sub = sp.get("sub") or (str(st) if st else "4")
    start = sp.get("start") or i
    box_a = start
    peak_i = start
    sc, slope, _sharp = sma_slope(ma, i, SR)
    hh, hl, ph, pl = struct(i)
    above = bool(c[i] > ma[i])
    an = above_n(i)
    crosses = int(np.sum(np.diff(np.sign(c[-31:] - ma[-31:])) != 0))
    sup = float(l[pl[-1]]) if pl else (sp.get("floor") or sp.get("adv_hl"))
    res = float(h[ph[-1]]) if ph else (sp.get("ceil") or sp.get("bo_level"))
    pos = "above" if (an >= cn and above) else "below" if (an <= cw - cn and not above) else "cross"
    struct_cls = "HH/HL" if (hh and hl) else "LH/LL" if (hh is False and hl is False) else "mixed"
    broke = bool(sup is not None and c[i] < sup)
    ceil, floor = sp.get("ceil"), sp.get("floor")
    # sub already comes from stage_path (2a / 2 / 1 / 3 / 4)
    if bench_w is not None and wk is not None and len(wk):
        rs_s = mansfield(wk["Close"], bench_w, R)
        rs_now = float(rs_s.iloc[-1]) if len(rs_s) else float("nan")
        prev_i = len(rs_s) - 1 - R["rs_rising_w"]
        rs_prev = float(rs_s.iloc[prev_i]) if prev_i >= 0 else float("nan")
    else:
        rs_now = rs_prev = float("nan")
    rs_up = bool(rs_now > rs_prev) if not (np.isnan(rs_now) or np.isnan(rs_prev)) else None
    sl_he = {"up": "עולה", "down": "יורד", "flat": "שטוח"}.get(sc or "", "?")
    pos_he = {"above": f"מעל הממוצע בעקביות ({an}/{cw} סגירות)", "below": f"מתחת לממוצע בעקביות ({an}/{cw} סגירות מעל)",
              "cross": f"חוצה את הממוצע הלוך ושוב ({an}/{cw} סגירות מעל, {crosses} חציות ב-30 ימים)"}[pos]
    st_he = {"HH/HL": "שיאים עולים ושפלים עולים (HH/HL)", "LH/LL": "שיאים יורדים ושפלים יורדים (LH/LL)", "mixed": "מבנה מעורב / דשדוש"}[struct_cls]

    def ck(key, ok, he):
        return {"k": key, "ok": None if ok is None else bool(ok), "he": he}
    fl = f"${floor:.2f}" if floor is not None else "—"
    ce = f"${ceil:.2f}" if ceil is not None else "—"
    checks = {
        1: [ck("pos", pos == "cross" or sub == "1T", f"מחיר מול SMA 150 יום: {pos_he} — שלב 1: חוצה הלוך ושוב"),
            ck("slope", sc == "flat", f"שיפוע הממוצע {sl_he} ({slope:+.2f}% ב-{SR['sma_slope_w']} ימי מסחר) — שלב 1: שטוח אחרי ירידה"),
            ck("struct", struct_cls != "LH/LL", f"מבנה: {st_he} — שלב 1: קופסת דשדוש"),
            ck("range", floor is not None and ceil is not None and floor <= c[i] <= ceil, f"בתוך הקופסה {fl}–{ce} (תמיכה / התנגדות)")],
        2: [ck("pos", pos == "above" or sub == "2a", f"מחיר מול SMA 150 יום: {pos_he} — שלב 2: מעל SMA 150 יום עולה (סגירה מתחתיו אינה שלב 2)"),
            ck("slope", sc == "up", f"שיפוע הממוצע {sl_he} ({slope:+.2f}% ב-{SR['sma_slope_w']} ימי מסחר) — שלב 2: עולה"),
            ck("struct", struct_cls == "HH/HL", f"מבנה: {st_he}"),
            ck("range", not broke, f"השפל העולה האחרון {('$%.2f' % sup) if sup else '—'} לא נשבר" + (" — נשבר" if broke else ""))],
        3: [ck("pos", pos == "cross", f"מחיר מול SMA 150 יום: {pos_he} — שלב 3: חוצה מטה ומעלה אחרי עלייה"),
            ck("slope", sc == "flat", f"שיפוע הממוצע {sl_he} ({slope:+.2f}% ב-{SR['sma_slope_w']} ימי מסחר) — שלב 3: מתיישר"),
            ck("struct", hh is not True, f"מבנה: {st_he} — שלב 3: כישלון בשיא גבוה משמעותית"),
            ck("range", floor is not None and ceil is not None and floor <= c[i] <= ceil, f"בתוך קופסת הפסגה {fl}–{ce}")],
        4: [ck("pos", pos == "below", f"מחיר מול SMA 150 יום: {pos_he} — שלב 4: מתחת בעקביות"),
            ck("slope", sc == "down", f"שיפוע הממוצע {sl_he} ({slope:+.2f}% ב-{SR['sma_slope_w']} ימי מסחר) — שלב 4: יורד (או נשברה תמיכה, גם אם הממוצע עוד שטוח)"),
            ck("struct", struct_cls == "LH/LL", f"מבנה: {st_he}"),
            ck("range", c[i] < (ceil or np.inf), f"מתחת לשיא היורד האחרון {ce} (שבר את תמיכת שלב 3)")],
    }[st]
    score = sum(1 for x in checks if x["ok"])
    td = IDX_TD[sub if sub in ("1T", "2a", "2-dip", "2-weak") else st]
    bo_out = None
    if sp.get("bo_level"):
        bo_out = {"level": _f(sp["bo_level"]), "vol_ratio": _f(sp.get("bo_vol"), 2),
                  "vol_ok": bool(sp.get("bo_vol") and sp["bo_vol"] >= R["vol_mult"])}
    return {
        "stage": st, "sub": sub, "score": score, "conf": "high" if score == 4 else "med" if score == 3 else "low",
        "checks": checks, "week": w.index[i].strftime("%Y-%m-%d"), "close": _f(c[i]), "ma30": _f(ma[i]),
        "ma150": _f(ma[i]), "ma50": _f(sp.get("ma10")),
        "slope": _f(slope), "slope_cls": sc, "pct_ma": _f((c[i] / ma[i] - 1) * 100, 1), "rs": _f(rs_now, 1),
        "rs_prev": _f(rs_prev, 1), "rs_up": rs_up, "hh": hh, "hl": hl,
        "weeks": len(wk) if wk is not None else n, "days": n, "tf": "daily", "ma_kind": "150d",
        "idx": {"pos": pos, "above_n": an, "of_w": cw, "crosses13": crosses, "struct": struct_cls,
                "swing_hi": [_f(h[j]) for j in ph[-2:]], "swing_lo": [_f(l[j]) for j in pl[-2:]],
                "swing_hi_w": [w.index[j].strftime("%Y-%m-%d") for j in ph[-2:]], "swing_lo_w": [w.index[j].strftime("%Y-%m-%d") for j in pl[-2:]],
                "support": _f(sup), "resistance": _f(res), "broke_support": broke, "td": td[0], "td_he": td[1]},
        "range": {"ceil": _f(ceil), "floor": _f(floor), "since_w": n - 1 - start, "since_d": n - 1 - start,
                  "since": w.index[start].strftime("%Y-%m-%d")},
        "bo": bo_out, "vol_ratio": _f(sp.get("vol_ratio"), 2),
    }


def market_gate(spy: Optional[Dict[str, Any]], R=RULES) -> Dict[str, Any]:
    """Rule 3 (Eyal 2026-11-15): SPY stage 3 or 4 -> no new long Buy-Stop. Stage 1 = caution (allowed), 2 = full."""
    if not spy:
        return {"ok": None, "he": "שוק (SPY): לא ידוע"}
    s = spy["stage"]
    ok = s not in R["mkt_block_stages"]
    return {"ok": ok, "he": f"שוק כללי (SPY) לא בשלב 3/4 — כעת {('שלב %s' % s)}{' (סוף שלב 1)' if spy.get('sub') == '1T' else ''}: {spy.get('idx', {}).get('td_he', '')}"}


def top_down(mkt: Optional[Dict[str, Any]], sec: Optional[Dict[str, Any]], R=RULES) -> Tuple[str, str]:
    """Rule 3 label per sector: (key, Hebrew)."""
    ms = (mkt or {}).get("stage")
    if ms in R["mkt_block_stages"]:
        return "mkt_off", f"שוק בשלב {ms} — לצמצם חשיפה, אין לונג חדש"
    if not sec:
        return "na", "לא ידוע"
    s, ok = sec["stage"], sec.get("sec_ok")
    if s == 4:
        return "avoid", "להימנע מהסקטור (שלב 4)"
    if s == 3:
        return "no_new", "אין לונג חדש (פסגה / הפצה)"
    if ok and sec.get("sec_case") == "2":
        return ("full", "הקצאה מלאה — פריצות אגרסיביות") if ms == 2 else ("caution", "שלב 2, אבל השוק בשלב 1 — זהירות")
    if ok:
        return "early", "זהירות — מובילות מוקדמות (סוף שלב 1)"
    return "wait", "להמתין — הסקטור לא עומד בכלל"


def short_market_gate(spy: Optional[Dict[str, Any]], R=RULES) -> Dict[str, Any]:
    """Short market gate: SPY in stage 3 or 4 permits shorts; stage 1 and stage 2 (including 2-weak, where SMA 150 יום is
    still rising) block new Sell-Stops unless short_mkt_allow_2weak."""
    if not spy:
        return {"ok": None, "he": "שוק לשורט (SPY): לא ידוע"}
    s, sub = spy["stage"], spy.get("sub")
    if s in R["short_mkt_allow_stages"]:
        return {"ok": True, "he": f"שוק לשורט (SPY) בשלב {s} — פתוח ל-Sell-Stop ({spy.get('idx', {}).get('td_he', '')})"}
    if sub == "2-weak":
        if R.get("short_mkt_allow_2weak"):
            return {"ok": True, "he": "שוק לשורט (SPY): שלב 2 בסיכון (2-weak) — זהירות"}
        return {"ok": False, "he": "שוק לשורט (SPY): שלב 2 בסיכון (2-weak — מתחת לממוצע ונשבר שפל, אך SMA 150 יום עדיין עולה) — ממתינים לשלב 3/4"}
    return {"ok": False, "he": f"שוק לשורט (SPY) בשלב {s} — לא בשלב 3/4, אין Sell-Stop חדש"}


def short_top_down(mkt: Optional[Dict[str, Any]], sec: Optional[Dict[str, Any]], R=RULES) -> Tuple[str, str]:
    """Top-down label per sector for shorts."""
    ms = (mkt or {}).get("stage")
    if ms not in R["short_mkt_allow_stages"]:
        return "mkt_off", f"שוק בשלב {ms} — אין Sell-Stop חדש"
    if not sec:
        return "na", "לא ידוע"
    s, ok = sec["stage"], sec.get("short_sec_ok")
    if s == 2:
        return "avoid", "להימנע משורט (שלב 2)"
    if s == 1:
        return "wait", "שלב 1 (בסיס) — להמתין"
    if ok and s == 4:
        return "full", "שלב 4 — הקצאה מלאה לשורט"
    if ok and s == 3:
        return "early", "שלב 3 (פסגה) — מועמד לשבירה (Sell-Stop)"
    return "wait", "להמתין — הסקטור לא עומד לשורט"


def write_candles(t: str, w: pd.DataFrame, R=RULES) -> None:
    """Weekly OHLCV of the last candle_weeks for the big chart (app/data/stages_candles/T.json), written only on change."""
    wc = w.iloc[-R["candle_weeks"]:]
    cj = json.dumps({"w": [[ix.strftime("%Y-%m-%d"), *(round(float(x), 2) for x in row[:4]), int(row[4])]
                           for ix, row in zip(wc.index, wc[["Open", "High", "Low", "Close", "Volume"]].values)]},
                    separators=(",", ":"))
    cp = OUT_CANDLES / f"{t}.json"
    if not cp.exists() or cp.read_text() != cj:
        cp.write_text(cj)


def spark(w: pd.DataFrame, weeks: int) -> Dict[str, Any]:
    ww = w.iloc[-(weeks + 30):].copy()
    ma = ww["Close"].rolling(30).mean().iloc[-weeks:]
    ww = ww.iloc[-weeks:]
    lo, hi = float(ww["Low"].min()), float(ww["High"].max())
    span = (hi - lo) or 1.0
    q = bytearray()
    for o, h, l, c in ww[["Open", "High", "Low", "Close"]].itertuples(index=False):
        q += bytes(max(0, min(255, int(round((float(x) - lo) / span * 255)))) for x in (o, h, l, c))
    m = bytes(255 if pd.isna(x) else max(0, min(254, int(round((float(x) - lo) / span * 254)))) for x in ma)
    return {"w0": ww.index[0].strftime("%Y-%m-%d"), "lo": round(lo, 2), "hi": round(hi, 2), "n": len(ww),
            "q": base64.b64encode(bytes(q)).decode(), "ma": base64.b64encode(m).decode()}


# ----------------------------------------------------------------------------------------------- build
def history_ok(w: pd.DataFrame, R=RULES) -> bool:
    """>= 3 years of completed weekly bars (min_weeks = 156; Eyal 2026-11-15, IEAG). Checked BEFORE classification."""
    return len(w) >= R["min_weeks"]


def avg_dollar_vol_m(d: Optional[pd.DataFrame] = None, w: Optional[pd.DataFrame] = None, R=RULES) -> Optional[float]:
    """Average daily dollar volume in millions (Eyal 2026-11-16, VBNK).
    Prefer the 50-day mean of close×volume from daily bars; if no daily data, weekly $vol / 5 averaged over ~10 weeks."""
    days = int(R.get("dollar_vol_days", 50))
    if d is not None and len(d) and "Close" in d.columns and "Volume" in d.columns:
        s = (pd.to_numeric(d["Close"], errors="coerce") * pd.to_numeric(d["Volume"], errors="coerce")).dropna()
        if len(s):
            return float(s.iloc[-min(days, len(s)):].mean() / 1e6)
    weeks = int(R.get("dollar_vol_weeks", 10))
    if w is not None and len(w) and "Close" in w.columns and "Volume" in w.columns:
        s = (pd.to_numeric(w["Close"], errors="coerce") * pd.to_numeric(w["Volume"], errors="coerce")).dropna()
        if len(s):
            return float((s.iloc[-min(weeks, len(s)):].mean() / 5.0) / 1e6)
    return None


def liquidity_ok(dv_m: Optional[float], R=RULES) -> bool:
    """Avg daily $vol >= $50M (Eyal 2026-11-16, VBNK). Checked BEFORE classification, like history_ok.
    Indexes and sector ETFs are not run through this gate."""
    return (dv_m or 0) >= R["min_dollar_vol_m"]


def cash_etf_ok(ticker: str, w: Optional[pd.DataFrame] = None, close: Optional[float] = None, R=RULES) -> bool:
    """Hard pre-filter (same rule as report_filters.f_not_cash_etf): exclude cash / money-market / short-bond ETFs
    and any fund whose weekly ATR(14) is < cash_etf_atr_pct_max % of price."""
    try:
        import report_filters as rf
        import stock_screen as ss
        cash_set = rf.CASH_BOND_ETFS
        is_fund = ss.is_fund(ticker)
    except Exception:
        cash_set = frozenset()
        is_fund = False
    t = ticker.upper()
    if t in cash_set:
        return False
    if is_fund and w is not None and len(w) >= 15:
        c = close if close is not None else float(w["Close"].iloc[-1])
        aw = weekly_atr(w)
        if aw is not None and c > 0 and (aw / c) * 100.0 < float(R.get("cash_etf_atr_pct_max", 1.0)):
            return False
    return True


def _short_float_fallback() -> Dict[str, float]:
    """Load cached short float percentages from fv_ownership.json and ownership_quote.json as offline fallback."""
    out: Dict[str, float] = {}
    for path, is_frac in ((Path("/workspace/cache/ownership_quote.json"), False),
                          (Path("/workspace/cache/fv_ownership.json"), True)):
        try:
            raw = json.loads(path.read_text())
        except Exception:
            continue
        items = raw.get("tickers", {}) if is_frac else raw
        for tk, rec in items.items():
            if not isinstance(rec, dict):
                continue
            v = rec.get("short_float") if is_frac else rec.get("short_float_pct")
            if v is not None:
                try:
                    f = float(v) * (100.0 if is_frac else 1.0)
                    if not math.isnan(f):
                        out[str(tk).upper()] = round(f, 2)
                except (TypeError, ValueError):
                    pass
    return out


def prefilter(u: Dict[str, Any], weeks: int, close: float, dollar_vol_m: Optional[float], R=RULES) -> List[Dict[str, Any]]:
    inst = u.get("inst_own")
    small_bio = (u.get("industry") == "Biotechnology") and (u.get("mcap") or 0) < R["biotech_cap_b"] * 1e9
    return [
        {"k": "price", "ok": close >= R["min_price"], "he": f"מחיר ≥ ${R['min_price']:.0f} (מינימום קשיח $10 בסריקה)"},
        {"k": "liq", "ok": bool((dollar_vol_m or 0) >= R["min_dollar_vol_m"]),
         "he": f"נזילות: מחזור יומי ממוצע ≥ ${R['min_dollar_vol_m']:.0f}M (ממוצע {int(R.get('dollar_vol_days', 50))} ימים של מחיר×כמות)"},
        {"k": "inst", "ok": None if inst is None else bool(R["inst_lo"] <= inst <= R["inst_hi"]), "he": "החזקה מוסדית 25%–85%"},
        {"k": "bio", "ok": not small_bio, "he": "לא ביוטק קטן (ביוטכנולוגיה מתחת ל-$2B שווי)"},
        {"k": "hist", "ok": weeks >= R["min_weeks"], "he": f"לפחות 3 שנות מסחר ({R['min_weeks']} נרות שבועיים)"},
    ]


def build(offline: bool = False, R=RULES) -> Dict[str, Any]:
    import stock_screen as ss
    today = datetime.now().date()
    if offline and UNIVERSE_CACHE.exists():
        uni = json.loads(UNIVERSE_CACHE.read_text())
    else:
        uni = fetch_universe()
    U = uni["rows"]
    tickers = sorted(U)
    etfs = sorted(set(MARKET) | set(SECTOR_ETF.values()) | set(INDUSTRY_ETF.values()) | set(INDUSTRY_WATCH) | {BENCH})
    hm = load_history(tickers + etfs, offline)
    last = ss.last_us_session_date()
    bw = weekly(hm[BENCH], last)["Close"] if BENCH in hm else None

    etf_out = {}
    for e in etfs:
        if e == BENCH or e not in hm:
            continue
        r = classify_index(hm[e], bw, R)  # daily 150d stage engine (Eyal 2026-11-27, t453u); gates follow this
        if r:
            etf_out[e] = {"name": ETF_NAMES.get(e, e), **{k: r[k] for k in ("stage", "sub", "score", "conf", "close", "ma30", "slope", "slope_cls", "pct_ma", "rs", "rs_up", "week", "checks", "hh", "hl", "idx")}}
            ss_ = sector_status(etf_out[e], R)
            etf_out[e].update(sec_ok=ss_["ok"], sec_case=ss_["case"], sec_he=ss_["he"], range=r.get("range"),
                              base=None, bo=None, weeks=r.get("weeks"), atr_w=_f(weekly_atr(weekly(hm[e], last)), 2))
    for e in etf_out:  # rule 3 (top-down) label per sector / market
        ss_short = short_sector_status(etf_out[e], R)
        etf_out[e].update(short_sec_ok=ss_short["ok"], short_sec_case=ss_short["case"], short_sec_he=ss_short["he"])
        tk, the = top_down(etf_out.get("SPY"), etf_out[e], R) if e not in MARKET else (etf_out[e]["idx"]["td"], etf_out[e]["idx"]["td_he"])
        stk, sthe = short_top_down(etf_out.get("SPY"), etf_out[e], R) if e not in MARKET else (etf_out[e]["idx"]["td"], etf_out[e]["idx"]["td_he"])
        etf_out[e].update(td=tk, td_he=the, short_td=stk, short_td_he=sthe)
    strong = sorted([e for e in SECTOR_ETF.values() if e in etf_out and etf_out[e]["stage"] == 2 and (etf_out[e]["rs"] or -99) > 0],
                    key=lambda e: -(etf_out[e]["rs"] or 0))[:3]
    weak_sec = sorted([e for e in SECTOR_ETF.values() if e in etf_out and etf_out[e]["stage"] in (3, 4) and (etf_out[e]["rs"] or 99) < 0],
                      key=lambda e: (etf_out[e]["rs"] or 0))[:3]
    mg = market_gate(etf_out.get("SPY"), R)
    short_mg = short_market_gate(etf_out.get("SPY"), R)
    sf_fallback = _short_float_fallback()

    rows, sparks, skipped, short_t, thin_t = [], {}, {"no_history": 0, "short_history": 0, "low_volume": 0, "cash_etf": 0}, [], []
    OUT_CANDLES.mkdir(parents=True, exist_ok=True)
    for t in tickers:
        u = U[t]
        df = hm.get(t)
        if df is None or getattr(df, "empty", True):
            skipped["no_history"] += 1
            continue
        w = weekly(df, last)
        if not history_ok(w, R):  # Eyal 2026-11-15: < 3 years of history -> not in any tab / the candidates at all
            skipped["short_history"] += 1
            short_t.append(t)
            continue
        d = df.copy(); d.index = pd.to_datetime(d.index)
        dv = avg_dollar_vol_m(d, w, R)
        if not liquidity_ok(dv, R):  # Eyal 2026-11-16 (VBNK): < $50M avg daily $vol -> not classified / listed
            skipped["low_volume"] += 1
            thin_t.append(t)
            continue
        if not cash_etf_ok(t, w, float(w["Close"].iloc[-1]), R):
            skipped["cash_etf"] += 1
            continue
        r = classify(df, bw, R)  # daily bars + 150d SMA; weekly find_breakout stays inside classify
        if r is None:
            skipped["short_history"] += 1
            continue
        ind_etf, sec_etf, etf = etf_gate(u.get("industry"), u.get("sector"))
        fv_earn = parse_earn(u.get("earn_raw", ""), today)
        state, cd = ss.earn_cache_lookup(t, today)  # the retest scanner's earnings cache, when it has a future date
        ei = earnings_info(fv_earn, earn_timing(u.get("earn_raw", "")), cd.isoformat() if cd else None, today, R)
        earn, td, timing = ei["next"], ei["td"], ei["timing"]
        in_live, earn_eff, live_fri = earnings_live_week(earn, timing, today)
        pre = prefilter(u, len(w), r["close"], dv, R)
        e = etf_out.get(etf) if etf else None
        entry = []
        if r.get("plan"):
            p = r["plan"]
            kind = p["kind"]
            rs_ok = r["checks"][3]["ok"] if r["stage"] == 2 else (r["rs"] is not None and r["rs"] > 0 and bool(r["rs_up"]))
            ov_he = (f"שמיים פתוחים: אין התנגדות תקורה ב-2 השנים האחרונות{' (שיא כל הזמנים)' if p['ath'] else ''} — יעד = כניסה + {R['min_rr']:g}×סיכון"
                     if p["open_sky"] else f"התנגדות תקורה קרובה ${p['overhead']} (+{p['overhead_pct']}% מהכניסה, שיא סווינג משמעותי ב-2 השנים)")
            entry = [
                {"k": "mkt", "ok": mg["ok"], "he": mg["he"]},
                {"k": "sector", "ok": None if not e else e["sec_ok"],
                 "he": (f"{'ענף' if ind_etf else 'סקטור'} {etf or '?'} לא בשלב 4: שלב 2 מובהק או סוף שלב 1 – התעוררות (מעל SMA 150 יום שהפסיק לרדת)"
                       + (f" — {e['sec_he']} (שלב {e['stage']}, {'מעל' if e['close'] > e['ma30'] else 'מתחת'} לממוצע, שיפוע {e['slope_cls']}, מבנה {e['idx']['struct']}; RS {e['rs']} מידע בלבד) · {e.get('td_he', '')}" if e else "")
                       + (f" · סקטור {sec_etf} שלב {etf_out[sec_etf]['stage']} (מידע)" if ind_etf and sec_etf and sec_etf in etf_out else ""))},
                {"k": "rs", "ok": rs_ok, "he": "Mansfield RS > 0 ועולה"},
                {"k": "chase", "ok": not p["chase"],
                 "he": f"לא רודפים: עד {R['buy_zone_pct']:g}% מעל רמת הפריצה ועד {R['max_pct_above_ma']:g}% מעל SMA 150 יום "
                       f"(סגירה {p['close_vs_level']:+}% מהרמה, {r['pct_ma']:+}% מהממוצע; Buy-Stop {p['entry_vs_ma']:+}% מהממוצע)"
                       + (" — רחוקה מדי / אל תרדוף" if p["chase"] else "")},
                {"k": "stop", "ok": not p["stop_wide"], "info": True, "he": f"מידע בלבד (לא פוסל): SL עד {R['max_stop_pct']:g}% מתחת לכניסה ({p['risk_pct']}%, מתחת ל{ {'low': 'שפל הבסיס', 'hl': 'שפל עולה (שפל הבסיס רחוק מדי)'}.get(p['stop_basis'], 'SMA 150 יום') })"
                 + (" — SL רחב מדי (מעט מניות)" if p["stop_wide"] else "")},
                {"k": "air", "ok": True if p["open_sky"] else None, "he": ov_he},
                {"k": "rr", "ok": None if p["rr"] is None else p["rr"] >= R["min_rr"],
                 "he": f"R:R ≥ {R['min_rr']:g} מה-Buy-Stop ליעד הראשון (1:{p['rr']})"},
                earn_check(ei, R),
            ]
            pg = None
            if ei["last_ago"] is not None and ei["last_ago"] <= R["post_earn_td"]:
                pg = post_earn_gap(d, w, ei["last_eff"], p["level"], R)
            pc = post_earn_check(ei, pg, r["close"], p["level"], R)
            if pc:
                entry.append(pc)
            if not p["open_sky"]:  # the overhead level itself is information; the R:R check decides
                entry[5]["ok"] = None if p["rr"] is None else p["rr"] >= R["min_rr"]
            if kind == "breakout":
                bo = r["bo"]
                entry[2:2] = [
                    {"k": "vol", "ok": bo["vol_ok"], "he": f"מחזור שבוע הפריצה ≥ {R['vol_mult']:g}x ממוצע 10 שבועות ({bo['vol_ratio']}x)"},
                    {"k": "close", "ok": None if bo["close_pos"] is None else bo["close_pos"] >= R["strong_close"],
                     "he": "סגירה חזקה: נר הפריצה נסגר ב-25% העליונים של הטווח"},
                ]
            else:
                base = r["base"]
                entry[2:2] = [
                    {"k": "base", "ok": base["mature"], "he": f"בסיס בוגר: תקרה מלפני {base['since_top_w']} ש׳, {base['weeks']} סגירות מתחתיה (≥{R['min_base_w']})"},
                    {"k": "near", "ok": 0 <= (base["dist_pct"] or 0) <= R["pre_bo_pct"],
                     "he": f"קרובה לתקרה: עד {R['pre_bo_pct']:g}% מתחת להתנגדות ({base['dist_pct']}%)"},
                    {"k": "ma_ok", "ok": r["close"] > r["ma30"] and r["slope_cls"] != "down",
                     "he": f"המחיר מעל SMA 150 יום שאינו יורד (שיפוע {r['slope_cls']})"},
                ]
        # 'info' checks (SL width, Eyal 2026-11-14 'don't disqualify for a wide stop') are shown but never gate
        bs = entry_pass(entry, pre)
        sf_val = u.get("short_float") if u.get("short_float") is not None else sf_fallback.get(t)
        short_entry = []
        if r.get("short_plan"):
            sp = r["short_plan"]
            skind = sp["kind"]
            srs_ok = r["checks"][3]["ok"] if r["stage"] == 4 else (r["rs"] is not None and r["rs"] < 0 and r["rs_up"] is False)
            sup_he = (f"שמיים פתוחים מטה: אין תמיכה משמעותית ב-2 השנים האחרונות{' (שפל תקופה)' if sp['atl'] else ''} — יעד = כניסה − {R['min_rr']:g}×סיכון"
                      if sp["open_sky"] else f"תמיכה קרובה מטה ${sp['support']} (-{sp['support_pct']}% מהכניסה, שפל סווינג משמעותי ב-2 השנים)")
            sf_ok = True if sf_val is None else (sf_val < R["short_float_max_pct"])
            sf_he = (f"שורט פלואט: לא ידוע (לא פוסל)" if sf_val is None
                     else f"שורט פלואט < {R['short_float_max_pct']:g}% ({sf_val:.1f}% — הימנעות משורט סקוויז)")
            short_entry = [
                {"k": "mkt", "ok": short_mg["ok"], "he": short_mg["he"]},
                {"k": "sector", "ok": None if not e else e["short_sec_ok"],
                 "he": (f"{'ענף' if ind_etf else 'סקטור'} {etf or '?'} בשלב 3 או 4 (לא שלב 2)"
                        + (f" — {e['short_sec_he']} (שלב {e['stage']}, {'מעל' if e['close'] > e['ma30'] else 'מתחת'} לממוצע, שיפוע {e['slope_cls']}, מבנה {e['idx']['struct']}; RS {e['rs']} מידע בלבד) · {e.get('short_td_he', '')}" if e else "")
                        + (f" · סקטור {sec_etf} שלב {etf_out[sec_etf]['stage']} (מידע)" if ind_etf and sec_etf and sec_etf in etf_out else ""))},
                {"k": "rs", "ok": srs_ok, "he": "Mansfield RS < 0 ויורד"},
                {"k": "chase", "ok": not sp["chase"],
                 "he": f"לא רודפים: עד {R['sell_zone_pct']:g}% מתחת לרמת השבירה ועד {R['max_pct_below_ma']:g}% מתחת ל-SMA 150 יום "
                       f"(סגירה {sp['close_vs_level']:+}% מהרמה, {r['pct_ma']:+}% מהממוצע; Sell-Stop {sp['entry_vs_ma']:+}% מהממוצע)"
                       + (" — רחוקה מדי / אל תרדוף" if sp["chase"] else "")},
                {"k": "sf", "ok": sf_ok, **({"info": True} if sf_val is None else {}), "he": sf_he},
                {"k": "stop", "ok": not sp["stop_wide"], "info": True,
                 "he": f"מידע בלבד (לא פוסל): SL עד {R['max_stop_pct']:g}% מעל הכניסה ({sp['risk_pct']}%, מעל { {'high': 'שיא הפסגה', 'lh': 'שיא יורד (שיא הפסגה רחוק מדי)'}.get(sp['stop_basis'], 'SMA 150 יום') })"
                       + (" — SL רחב מדי (מעט מניות)" if sp["stop_wide"] else "")},
                {"k": "air", "ok": True if sp["open_sky"] else (None if sp["rr"] is None else sp["rr"] >= R["min_rr"]), "he": sup_he},
                {"k": "rr", "ok": None if sp["rr"] is None else sp["rr"] >= R["min_rr"],
                 "he": f"R:R ≥ {R['min_rr']:g} מה-Sell-Stop ליעד הראשון (1:{sp['rr']})"},
                earn_check(ei, R, "Sell-Stop"),
            ]
            pg_s = None
            if ei["last_ago"] is not None and ei["last_ago"] <= R["post_earn_td"]:
                pg_s = post_earn_gap_down(d, w, ei["last_eff"], sp["level"], R)
            pc_s = post_earn_short_check(ei, pg_s, r["close"], sp["level"], R)
            if pc_s:
                short_entry.append(pc_s)
            if skind == "breakdown":
                bd = r["bd"]
                short_entry[2:2] = [
                    {"k": "vol", "ok": bd["vol_ok"], "info": True,
                     "he": f"מידע בלבד (לא חובה בשורט): מחזור שבוע השבירה {bd['vol_ratio']}x ממוצע 10 ש׳ (רצוי ≥ {R['vol_mult']:g}x)"},
                    {"k": "close", "ok": None if bd["close_pos"] is None else bd["close_pos"] <= (1 - R["strong_close"]),
                     "he": "סגירה חלשה: נר השבירה נסגר ב-25% התחתונים של הטווח"},
                ]
            else:
                sbase = r["short_base"]
                short_entry[2:2] = [
                    {"k": "base", "ok": sbase["mature"],
                     "he": f"פסגה / בסיס בוגר: תמיכה מלפני {sbase['since_bot_w']} ש׳, {sbase['weeks']} סגירות מעליה (≥{R['min_base_w']})"},
                    {"k": "near", "ok": 0 <= (sbase["dist_pct"] or 0) <= R["pre_bo_pct"],
                     "he": f"קרובה לתמיכה: עד {R['pre_bo_pct']:g}% מעל הרצפה ({sbase['dist_pct']}%)"},
                    {"k": "ma_ok", "ok": r["close"] < r["ma30"] and r["slope_cls"] != "up",
                     "he": f"המחיר מתחת ל-SMA 150 יום שאינו עולה (שיפוע {r['slope_cls']})"},
                ]
        ss_flag = entry_pass(short_entry, pre)
        rows.append({
            "t": t, "n": u.get("company"), "ex": u.get("exchange"), "sec": u.get("sector"), "ind": u.get("industry"),
            "etf": etf, "etf_stage": e["stage"] if e else None, "etf_rs": e["rs"] if e else None,
            "etf_td": e.get("td") if e else None, "etf_td_he": e.get("td_he") if e else None,
            "short_etf_td": e.get("short_td") if e else None, "short_etf_td_he": e.get("short_td_he") if e else None,
            "ind_etf": ind_etf, "sec_etf": sec_etf,
            "sec_etf_stage": etf_out[sec_etf]["stage"] if sec_etf and sec_etf in etf_out else None,
            "mcap_b": _f((u.get("mcap") or 0) / 1e9, 1) if u.get("mcap") else None, "inst": u.get("inst_own"),
            "short_float": _f(sf_val, 1) if sf_val is not None else None,
            "dv_m": _f(dv, 1), "atr_w": _f(weekly_atr(w), 2), "earn": earn, "earn_td": td, **r, "pre": [{"k": x["k"], "ok": x["ok"]} for x in pre], "pre_ok": all(x["ok"] is not False for x in pre),
            "earn_eff": ei["eff"], "earn_timing": timing, "earn_live_week": in_live, "earn_est": ei["est"],
            "earn_last": ei["last"], "earn_last_ago": ei["last_ago"],
            "earn_block": bool(earn and td is not None and td <= R["earn_td"]),
            "post_earn": next((x["he"] for x in entry if x["k"] == "post"), None),
            "post_gap": bool(next((x for x in entry if x["k"] == "post" and x["ok"] is False), None)),
            "post_earn_short": next((x["he"] for x in short_entry if x["k"] == "post"), None),
            "post_gap_short": bool(next((x for x in short_entry if x["k"] == "post" and x["ok"] is False), None)),
            "entry": entry, "entry_ok": bs, "bs": bs,
            "short_entry": short_entry, "short_entry_ok": ss_flag, "ss": ss_flag,
        })
        sparks[t] = spark(w, R["spark_weeks"])
        write_candles(t, w, R)
    for e in etf_out:  # sector / market ETFs: spark + big-chart candles (#/stages/XLU, Eyal 2026-11-14)
        if e in hm:
            we = weekly(hm[e], last)
            sparks[e] = spark(we, R["spark_weeks"])
            write_candles(e, we, R)
    counts = {str(s): sum(1 for x in rows if x["stage"] == s) for s in (1, 2, 3, 4)}
    counts["2A"] = sum(1 for x in rows if str(x.get("sub") or "") in ("2A", "2a"))
    counts["4A"] = sum(1 for x in rows if x["sub"] == "4A")
    cands = sorted((x for x in rows if x["bs"]), key=lambda x: -(x["plan"]["rr"] or 0))
    short_cands = sorted((x for x in rows if x["ss"]), key=lambda x: -(x["short_plan"]["rr"] or 0))
    counts["bs"] = len(cands)
    counts["ss"] = len(short_cands)
    doc = {
        "version": 1, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "week": max((x["week"] for x in rows), default=None), "rules": R, "screens": SCREENS,
        "finviz_totals": uni.get("totals"), "finviz_fetched_at": uni.get("fetched_at"), "skipped": skipped,
        "short_history_tickers": short_t, "low_volume_tickers": thin_t,
        "market": {k: etf_out[k] for k in MARKET if k in etf_out}, "market_gate": mg, "short_market_gate": short_mg,
        "sectors": {k: etf_out[k] for k in etf_out if k in set(SECTOR_ETF.values())},
        "industries": {k: etf_out[k] for k in etf_out if k not in MARKET and k not in set(SECTOR_ETF.values())},
        "strong_sectors": strong, "weak_sectors": weak_sec,
        "strong_industries": sorted([e for e in set(INDUSTRY_ETF.values()) | set(INDUSTRY_WATCH)
                                     if e in etf_out and etf_out[e]["stage"] == 2 and (etf_out[e]["rs"] or -99) > 0],
                                    key=lambda e: -(etf_out[e]["rs"] or 0))[:5],
        "weak_industries": sorted([e for e in set(INDUSTRY_ETF.values()) | set(INDUSTRY_WATCH)
                                   if e in etf_out and etf_out[e]["stage"] in (3, 4) and (etf_out[e]["rs"] or 99) < 0],
                                  key=lambda e: (etf_out[e]["rs"] or 0))[:5],
        "pre_he": {x["k"]: x["he"] for x in prefilter({}, 0, 0.0, None, R)},  # row 'pre' = [{k, ok}] (text once here)
        "counts": counts, "rows": rows,
        "buy_stop_candidates": [candidate(x) for x in cands],
        "sell_stop_candidates": [short_candidate(x) for x in short_cands],
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    OUT_SPARK.write_text(json.dumps(sparks, separators=(",", ":")))
    print(f"[stages] {len(rows)} stocks, counts {counts}, skipped {skipped} -> {OUT} ({OUT.stat().st_size // 1024} KB), "
          f"{OUT_SPARK.name} ({OUT_SPARK.stat().st_size // 1024} KB)")
    # Sector board (T-7): 11 SPDR ETFs + top-10 daily charts + filter lists. Nightly --publish picks this up.
    from srs_app.sector_board import write_board
    write_board(doc, hm, offline=offline)
    return doc


def candidate(x: Dict[str, Any]) -> Dict[str, Any]:
    p = x["plan"]
    return {"t": x["t"], "n": x["n"], "kind": p["kind"], "sub": x["sub"], "close": x["close"], "level": p["level"],
            "buy_stop": p["entry"], "stop": p["stop"], "stop_pct": p["risk_pct"], "target": p["target"],
            "target_src": p["target_src"], "open_sky": p["open_sky"], "rr": p["rr"], "shares": p["shares"],
            "pos_usd": p["pos_usd"], "vol_need": p.get("vol_need"), "earn": x["earn"], "earn_td": x["earn_td"],
            "earn_est": x.get("earn_est", False), "post_earn": x.get("post_earn"), "ex": x["ex"],
            "etf": x.get("etf"), "etf_stage": x.get("etf_stage"), "sec_td_he": x.get("etf_td_he")}


def short_candidate(x: Dict[str, Any]) -> Dict[str, Any]:
    p = x["short_plan"]
    return {"t": x["t"], "n": x["n"], "kind": p["kind"], "sub": x["sub"], "close": x["close"], "level": p["level"],
            "sell_stop": p["entry"], "stop": p["stop"], "stop_pct": p["risk_pct"], "target": p["target"],
            "target_src": p["target_src"], "open_sky": p["open_sky"], "rr": p["rr"], "shares": p["shares"],
            "pos_usd": p["pos_usd"], "atr_w": x.get("atr_w"),
            "vol_ratio": (x.get("bd") or {}).get("vol_ratio"), "short_float": x.get("short_float"),
            "earn": x["earn"], "earn_td": x["earn_td"], "earn_est": x.get("earn_est", False),
            "post_earn": x.get("post_earn_short"), "ex": x["ex"],
            "etf": x.get("etf"), "etf_stage": x.get("etf_stage"), "sec_td_he": x.get("short_etf_td_he")}


KIND_HE = {"breakout": "פריצה טרייה (באזור קנייה)", "trigger": "בסיס שלב 1 מתחת לתקרה", "continuation": "בסיס המשך בשלב 2"}
SHORT_KIND_HE = {"breakdown": "שבירה טרייה (4A)", "trigger": "פסגת שלב 3 מעל תמיכה", "continuation": "בסיס המשך בשלב 4"}


def _earn_alert_str(c: Dict[str, Any]) -> str:
    if not c.get("earn"):
        return "לא ידוע"
    est = " (משוער)" if c.get("earn_est") else ""
    td = f" — בעוד {c['earn_td']} ימ״ס" if c.get("earn_td") is not None else ""
    return f"{c['earn']}{est}{td}"


def alert_text(doc: Dict[str, Any], research: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Hebrew Telegram text for Buy-Stop + Sell-Stop candidates (None = nothing actionable -> no message)."""
    cs = doc.get("buy_stop_candidates") or []
    scs = doc.get("sell_stop_candidates") or []
    if not cs and not scs:
        return None
    R = doc["rules"]
    lines: List[str] = []
    mk = doc.get("market") or {}
    mkt_line = None
    if mk.get("SPY"):  # rule 3: the market stage + its top-down meaning (QQQ as info)
        q = mk.get("QQQ")
        mkt_line = (f"שוק: SPY שלב {mk['SPY']['stage']} — {mk['SPY'].get('idx', {}).get('td_he', '')}"
                    + (f" · QQQ שלב {q['stage']} (מידע)" if q else ""))
    if cs:
        lines.append(f"🟢 שיטת סטף — מועמדות ל-Buy-Stop (שבוע {doc['week']}): {len(cs)}")
        if mkt_line:
            lines.append(mkt_line)
            mkt_line = None
        lines.append("")
        for c in cs:
            tgt = f"${c['target']}" + (" (שמיים פתוחים · R:R 2.5)" if c["open_sky"] else " (התנגדות תקורה)")
            lines += [f"{c['t']} · {KIND_HE.get(c['kind'], c['kind'])}",
                      f"Buy-Stop ${c['buy_stop']} · סטופ ${c['stop']} ({c['stop_pct']}%) · יעד {tgt}",
                      f"R:R 1:{c['rr']} · {c['shares']} מניות לסיכון ${R['risk_usd']:g} (${c['pos_usd']}) · דוח {_earn_alert_str(c)}"]
            if c.get("post_earn"):
                lines.append(c["post_earn"])
            if c.get("sec_td_he"):
                lines.append(f"סקטור {c.get('etf')}: שלב {c.get('etf_stage')} — {c['sec_td_he']}")
            rs = (research or {}).get(c["t"], {}).get("data", {})
            if rs.get("short_he"):
                lines.append(f"📊 {rs['short_he']} ({rs.get('as_of', '')})")
            if c["kind"] != "breakout" and c.get("vol_need"):
                lines.append(f"תנאי: מחזור שבוע הפריצה ≥ {R['vol_mult']:g}x ממוצע 10 ש׳ (≥ {int(c['vol_need']):,} מניות) — אחרת פריצת שווא")
            lines.append("")
    if scs:
        lines.append(f"🔴 שיטת סטף — מועמדי שורט / Sell-Stop (שבוע {doc['week']}): {len(scs)}")
        if mkt_line:
            lines.append(mkt_line)
        lines.append("")
        for c in scs:
            tgt = f"${c['target']}" + (" (שמיים פתוחים מטה · R:R 2.5)" if c["open_sky"] else " (תמיכה קרובה)")
            atr_txt = f" · ATR(W) ${c['atr_w']}" if c.get("atr_w") is not None else ""
            lines += [f"{c['t']} · {SHORT_KIND_HE.get(c['kind'], c['kind'])}",
                      f"Sell-Stop ${c['sell_stop']} · סטופ ${c['stop']} ({c['stop_pct']}%) · יעד {tgt}",
                      f"R:R 1:{c['rr']} · {c['shares']} מניות לסיכון ${R['risk_usd']:g} (${c['pos_usd']}){atr_txt} · דוח {_earn_alert_str(c)}"]
            if c.get("post_earn"):
                lines.append(c["post_earn"])
            if c.get("sec_td_he"):
                lines.append(f"סקטור {c.get('etf')}: שלב {c.get('etf_stage')} — {c['sec_td_he']}")
            rs = (research or {}).get(c["t"], {}).get("data", {})
            if rs.get("short_he"):
                lines.append(f"📊 {rs['short_he']} ({rs.get('as_of', '')})")
            lines.append("")
    lines.append("בלי פקודות אוטומטיות — רק התראה. https://retest-scanner.vercel.app/#/stages")
    return "\n".join(lines)


TG_CHAT_FILE = Path("/workspace/cache/telegram_chat_id")


def send_alert(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Telegram (same bot + chat as the retest price alerts). Token from env TELEGRAM_BOT_TOKEN (never printed); chat id
    from env TELEGRAM_CHAT_ID or /workspace/cache/telegram_chat_id. Sends only when there is a candidate."""
    import os
    import requests
    text = alert_text(doc, research_cache())
    if not text:
        return {"sent": False, "why": "no candidates"}
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID") or (TG_CHAT_FILE.read_text().strip() if TG_CHAT_FILE.exists() else "")
    if not tok or not chat:
        return {"sent": False, "why": "missing TELEGRAM_BOT_TOKEN or chat id"}
    ids, why = [], None
    for part in split_message(text):  # Telegram caps a message at 4096 chars: split between candidates
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=30,
                          json={"chat_id": chat, "text": part, "disable_web_page_preview": True})
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not j.get("ok"):
            why = j.get("description"); break
        ids.append((j.get("result") or {}).get("message_id"))
    return {"sent": bool(ids) and why is None, "message_ids": ids, "why": why,
            "n": len(doc.get("buy_stop_candidates") or []), "n_short": len(doc.get("sell_stop_candidates") or [])}


def split_message(text: str, limit: int = 3900) -> List[str]:
    """Split at blank lines (between candidates) into parts <= limit chars."""
    parts, cur = [], ""
    for block in text.split("\n\n"):
        add = block if not cur else cur + "\n\n" + block
        if len(add) <= limit:
            cur = add
            continue
        if cur:
            parts.append(cur)
        while len(block) > limit:
            parts.append(block[:limit]); block = block[limit:]
        cur = block
    if cur:
        parts.append(cur)
    return parts


# ----------------------------------------------------------------------------------------------- research
# Fundamental overview of every Buy-Stop candidate (Eyal 2026-11-14). Same store as the retest PASS overviews:
# Supabase public.ticker_research (data.scope = 'stage_overview', data.short_he = one line for the card + Telegram,
# data.consensus / eps_est / valuation ...), written by the bot (Supabase MCP), never by the app. The bot researches
# (FinViz / Yahoo / MarketBeat ..., real numbers only, missing = 'לא נמצא'), saves a JSON file and runs --research-save,
# which keeps a local copy (RESEARCH_CACHE: the Telegram alert reads short_he from it) and writes the upsert SQL.
RESEARCH_CACHE = Path("/workspace/cache/stage_research.json")
RESEARCH_SQL = Path("/workspace/cache/stage_research_upsert.sql")
RESEARCH_MAX_AGE_D = 7


def research_cache() -> Dict[str, Any]:
    try:
        return json.loads(RESEARCH_CACHE.read_text())
    except (OSError, ValueError):
        return {}


def needs_research(doc: Dict[str, Any], cache: Dict[str, Any], today: Optional[date] = None, max_age_d: int = RESEARCH_MAX_AGE_D) -> List[Dict[str, Any]]:
    """Candidates without an overview, or with one older than max_age_d days."""
    today = today or datetime.now().date()
    out = []
    seen = set()
    for c in (doc.get("buy_stop_candidates") or []) + (doc.get("sell_stop_candidates") or []):
        if c["t"] in seen:
            continue
        seen.add(c["t"])
        r = cache.get(c["t"])
        asof = (r or {}).get("data", {}).get("as_of")
        age = (today - date.fromisoformat(asof)).days if asof else None
        if age is None or age > max_age_d:
            out.append({"t": c["t"], "n": c.get("n"), "close": c.get("close"), "why": "חסרה" if age is None else f"בת {age} ימים"})
    return out


def _sql_str(x: Optional[str]) -> str:
    return "null" if x is None else "'" + str(x).replace("'", "''") + "'"


def research_upsert_sql(rows: List[Dict[str, Any]]) -> str:
    vals = []
    for r in rows:
        src = "array[" + ",".join(_sql_str(u) for u in (r.get("sources") or [])) + "]::text[]"
        vals.append(f"({_sql_str(r['ticker'])}, {_sql_str(r['summary_he'])}, {_sql_str(json.dumps(r['data'], ensure_ascii=False))}::jsonb, {src}, now())")
    return ("insert into public.ticker_research (ticker, summary_he, data, sources, updated_at) values\n" + ",\n".join(vals)
            + "\non conflict (ticker) do update set summary_he = excluded.summary_he, data = excluded.data, sources = excluded.sources, updated_at = now();\n")


def research_save(path: Path) -> Dict[str, Any]:
    rows = json.loads(Path(path).read_text())
    rows = rows if isinstance(rows, list) else [rows]
    for r in rows:
        assert r.get("ticker") and r.get("summary_he") and isinstance(r.get("data"), dict), "ticker / summary_he / data required"
        r["data"].setdefault("scope", "stage_overview")
        r["data"].setdefault("as_of", datetime.now().date().isoformat())
    cache = research_cache()
    for r in rows:
        cache[r["ticker"]] = r
    RESEARCH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RESEARCH_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    RESEARCH_SQL.write_text(research_upsert_sql(rows))
    return {"saved": [r["ticker"] for r in rows], "sql": str(RESEARCH_SQL)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--alert", action="store_true", help="Telegram the Buy-Stop candidates (only when there are any)")
    ap.add_argument("--needs-research", action="store_true", help="list candidates (current stages.json) without a fresh overview")
    ap.add_argument("--research-save", metavar="JSON", help="store overviews (list of {ticker, summary_he, data, sources}) + write upsert SQL")
    ap.add_argument("--alert-only", action="store_true", help="Telegram from the current stages.json (no rebuild)")
    a = ap.parse_args()
    sys.path.insert(0, str(REPO))
    if a.research_save:
        print(json.dumps(research_save(Path(a.research_save)), ensure_ascii=False))
        return
    if a.needs_research or a.alert_only:
        doc = json.loads(OUT.read_text())
        if a.needs_research:
            print(json.dumps(needs_research(doc, research_cache()), ensure_ascii=False))
        if a.alert_only:
            print(json.dumps(send_alert(doc), ensure_ascii=False))
        return
    doc = build(a.offline)
    print(f"[stages] Buy-Stop candidates: {len(doc['buy_stop_candidates'])} " + ", ".join(c["t"] for c in doc["buy_stop_candidates"]))
    print(f"[stages] Sell-Stop candidates: {len(doc['sell_stop_candidates'])} " + ", ".join(c["t"] for c in doc["sell_stop_candidates"]))
    if a.publish:
        from srs_app.publish_data import publish
        r = publish(REPO / "app" / "data")
        print(json.dumps(r, ensure_ascii=False))
        if r.get("failed"):
            sys.exit(1)
    if a.alert:
        print(json.dumps(send_alert(doc), ensure_ascii=False))


if __name__ == "__main__":
    main()
