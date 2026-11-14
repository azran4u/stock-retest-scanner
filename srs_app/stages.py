"""Stan Weinstein stage analysis page (#/stages, Eyal 2026-11-13).

Separate pipeline: its own FinViz screen, its own history cache, its own data file. It never touches the retest
screen, gates, expert zones, drawings or alerts.

Rules = Eyal's masterclass page (Weinstein, 'Secrets for Profiting in Bull and Bear Markets'): weekly (Friday) closes
only, 30-week SMA + its slope, breakout volume >= 2x the 10-week average, Mansfield RS vs the S&P 500 > 0 and rising,
top-down market (SPY / QQQ / IWM) + sector ETF stage, pre-filter (price, liquidity, inst own 25-85%, NYSE / NASDAQ,
no small biotech, >= 40 weeks, no heavy overhead within 20%), stop below the last structural low AND the 30W SMA,
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
FV_COLS = "1,2,3,4,6,28,63,65,68"
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
INDUSTRY_ETF = {"Semiconductors": "SMH", "Semiconductor Equipment & Materials": "SMH"}
ETF_NAMES = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "XLK": "טכנולוגיה", "XLF": "פיננסים",
             "XLV": "בריאות", "XLE": "אנרגיה", "XLI": "תעשייה", "XLY": "צריכה מחזורית", "XLP": "צריכה בסיסית",
             "XLU": "תשתיות", "XLB": "חומרי גלם", "XLRE": "נדל\"ן", "XLC": "תקשורת", "SMH": "שבבים"}

RULES: Dict[str, Any] = {
    "ma_weeks": 30,              # 30-week SMA of weekly closes
    "slope_lookback_w": 5,       # slope = % change of the 30W SMA over the last 5 weeks
    "slope_flat_pct": 1.0,       # |5-week change| <= 1.0% = flat; > +1% rising; < -1% declining
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
    "max_pct_above_ma": 25.0,    # ... AND <= 30W SMA + 25% (Eyal 2026-11-14, XERS example); else 'רחוקה מדי / אל תרדוף'
    "range_max_w": 52,           # stage 1 / 3 trading range = high / low since the stage began (10-52 weeks)
    "extended_pct": 35.0,        # stage 2 'over-extended' = close > 35% above the 30W SMA (partial exit zone)
    "stop_buffer_pct": 0.7,      # stop = 0.7% under the 30W SMA, or under a valid (never broken) swing low ABOVE it; never under the SMA
    "max_stop_pct": 10.0,        # stop farther than 10% under the entry = 'SL רחב מדי' flag (info only, never disqualifies)
    "buy_stop_buf_pct": 0.5,     # Buy-Stop = base resistance + 0.5% (min $0.05) -- 'slightly above the ceiling'
    "buy_stop_min_buf": 0.05,
    "pre_bo_pct": 5.0,           # pre-breakout Buy-Stop setup: last close within 5% under the base resistance
    "min_rr": 2.5,               # R:R from the Buy-Stop entry to the nearest overhead resistance >= 2.5 (Eyal 2026-11-14)
    "overhead_w": 104,           # overhead resistance = significant swing highs of the last 2 years (104 weeks)
    "cong_min_w": 5,             # info: trading block = >= 5 weekly closes inside a 3% band above the entry
    "cong_band_pct": 3.0,
    "earn_td": 10,               # no new Buy-Stop when the report session is within the next 10 trading days (Eyal 2026-11-14:
                                 # the report week AND the week before; an after-close report counts on the next session)
    "earn_est_days": 91,         # FinViz has only a PAST date -> next report estimated at +13 weeks ('משוער'), blocks too
    "post_earn_td": 5,           # a report in the last 5 sessions -> post-earnings rules (gap-up / back to the Buy-Stop)
    "gap_min_pct": 2.0,          # post-earnings gap-up = open >= 2% above the prior close, close above the resistance,
    "gap_vol_mult": 2.0,         # ... on >= 2x the 20-day average volume -> don't chase, wait for a hold / mini-base
    "gap_vol_avg_d": 20,
    "mini_base_d": 3,            # ... candidate again after >= 3 sessions after the gap day all closing above the level
    "min_price": 15.0, "hard_min_price": 10.0, "min_dollar_vol_m": 30.0, "min_week_vol": 500_000,
    "inst_lo": 25.0, "inst_hi": 85.0, "min_weeks": 40, "biotech_cap_b": 2.0,
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
                    "mcap": _num(g("marketCap")), "inst_own": _num(g("instOwn")), "avg_vol": _num(g("averageVolume")),
                    "fv_price": _num(g("price")), "earn_raw": g("earningsDate")})
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
    closes at / under it (a real base: stage 1 -> 2 or a stage-2 continuation base), close > 30W SMA and the SMA not
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
                "base_weeks": base, "base_low": float(lo_base), "res_week": w.index[top_i].strftime("%Y-%m-%d"),
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
    return {"top": top, "low": blo, "weeks": cnt, "top_week": w.index[top_i].strftime("%Y-%m-%d"),
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


def trade_levels(w: pd.DataFrame, ma_now: float, entry: float, resistance: Optional[float], base_low: Optional[float],
                 R=RULES) -> Dict[str, Any]:
    """Stop just under the 30W SMA, or just under a valid (never broken) swing low above it (never under the SMA); first target = nearest overhead resistance of the last 2 years
    (significant weekly swing high); none = open sky -> target = entry + min_rr x risk (R:R exactly 2.5, Eyal 2026-11-14)."""
    l = w["Low"].values
    n = len(w)
    # Eyal 2026-11-14 (final): default stop = just under the 30W SMA; a clear VALID swing low (weekly pivot low of the
    # last 26 weeks, never broken afterwards) ABOVE the SMA and below the entry -> just under that low (smaller SL).
    # Never under the SMA: stop = max(SMA, valid low above it) x (1 - 0.7%). A broken low is never used.
    valid = [i for i in pivots(l, R["pivot_w"], False)
             if i >= n - 26 and ma_now < l[i] < entry and (i == n - 1 or l[i] < l[i + 1:].min())]
    swing_low = float(l[valid[-1]]) if valid else None
    basis = "low" if swing_low is not None else "ma"
    stop = max(ma_now, swing_low or 0.0) * (1 - R["stop_buffer_pct"] / 100)
    ov = overhead_scan(w, entry, R)
    risk = entry - stop
    target, tsrc = (ov["overhead"], "overhead") if ov["overhead"] else (None, None)
    if target is None and risk > 0:  # open sky (Eyal 2026-11-14): trade bar at exactly R:R = min_rr
        target, tsrc = entry + R["min_rr"] * risk, "open_sky"
    rr = (target - entry) / risk if (target and risk > 0 and target > entry) else None
    shares = int(R["risk_usd"] // risk) if risk > 0 else None
    stop_pct = risk / entry * 100 if entry else None
    return {"entry": _f(entry), "stop": _f(stop), "stop_basis": basis, "swing_low": _f(swing_low), "target": _f(target), "target_src": tsrc,
            "risk_pct": _f(stop_pct, 1), "stop_wide": bool(stop_pct is not None and stop_pct > R["max_stop_pct"]),
            "rr": _f(rr), "shares": shares, "pos_usd": _f(shares * entry, 0) if shares else None,
            "overhead": _f(ov["overhead"]), "overhead_pct": _f(ov["overhead_pct"], 1), "open_sky": ov["open_sky"],
            "ath": ov["ath"], "cong": _f(ov["cong"]), "hi2y": _f(ov["hi2y"]), "ov_levels": [_f(x) for x in ov["levels"]]}


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


def earn_check(ei: Dict[str, Any], R=RULES) -> Dict[str, Any]:
    """Not in a trade: no new Buy-Stop while the report session is within the next earn_td sessions (blocks on an
    estimated date too, labelled). Unknown date -> ok None (can't confirm)."""
    if not ei["next"]:
        return {"k": "earn", "ok": None, "he": "תאריך הדוח הבא לא ידוע — לבדוק לפני הצבת Buy-Stop"}
    lab = " (משוער: הדוח האחרון + 13 ש׳)" if ei["est"] else ""
    when = f"{ei['next']}{' אחרי הסגירה' if ei['timing'] == 'a' else ' לפני הפתיחה' if ei['timing'] == 'b' else ''}{lab}"
    if ei["td"] <= R["earn_td"]:
        return {"k": "earn", "ok": False, "he": f"דוח בעוד {ei['td']} ימי מסחר – לא להציב Buy-Stop (דוח {when})"}
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


def stage_path(w: pd.DataFrame, ma: np.ndarray, R=RULES) -> Dict[str, Any]:
    """Range-based stage state machine (Eyal 2026-11-14): inside a base / trading range crossings of the 30W SMA mean
    nothing. Stage 1 (base after a decline) -> 2 only on a weekly close above the range ceiling with the SMA flat / rising;
    -> 4 only on a close below the range floor. Stage 3 (top after an advance) -> 4 on a close below its floor, -> 2 on a
    close above its ceiling (SMA flat / rising). Stage 2 stays 2 (a continuation base included) until a close below the
    floor of its current base with the SMA no longer rising (-> 3, or -> 4 when the SMA declines), or until the SMA goes
    flat while price has made no new 26-week high for >= 10 weeks (-> 3: a top; a continuation base keeps a rising SMA). Stage 4 -> 1 once the
    SMA stops declining (or straight to 2 on a close above its last bounce high with a non-declining SMA)."""
    h, l, c = (w[k].values.astype(float) for k in ("High", "Low", "Close"))
    n = len(w)
    i0 = R["ma_weeks"] + R["slope_lookback_w"] - 1
    st, start = None, i0
    for i in range(i0, n):
        sc, _ = slope_class(ma, i, R)
        if sc is None:
            continue
        if st is None:
            st = 2 if sc == "up" else 4 if sc == "down" else (1 if c[i] < ma[i] else 3)
            start = i
            continue
        new = st
        if st in (1, 3):
            ceil, floor = _range(h, l, i, start, st, R)
            if c[i] > ceil and sc != "down":
                new = 2
            elif c[i] < floor and sc != "up":
                new = 4
        elif st == 2:
            a0 = max(0, i - R["base_window_w"])
            since_hi = i - (a0 + int(np.argmax(h[a0:i + 1])))
            if sc != "up" and c[i] < _trend_edge(h, l, i, True, R):
                new = 4 if sc == "down" else 3
            elif sc == "flat" and since_hi >= R["min_base_w"]:
                new = 3  # SMA lost its rise during a >= 10-week range = a top, not a continuation base
        elif st == 4:
            if sc != "down" and c[i] > _trend_edge(h, l, i, False, R):
                new = 2
            elif sc != "down":
                new = 1
        if new != st:
            st, start = new, i
    i = n - 1
    if st in (1, 3):
        ceil, floor = _range(h, l, i + 1, start, st, R)
    elif st == 2:
        ceil, floor = float(h[max(0, i + 1 - R["base_window_w"]):].max()), _trend_edge(h, l, i + 1, True, R)
    else:
        ceil, floor = _trend_edge(h, l, i + 1, False, R), float(l[max(0, i + 1 - R["base_window_w"]):].min())
    return {"stage": st, "start": start, "since_w": n - 1 - start, "ceil": ceil, "floor": floor}


def classify(w: pd.DataFrame, bench_w: Optional[pd.Series], R=RULES) -> Optional[Dict[str, Any]]:
    """Stage of the last completed week + the module-3 identification checks of that stage."""
    n = len(w)
    if n < R["ma_weeks"] + R["slope_lookback_w"]:
        return None
    c, h, l, v = (w[k].values.astype(float) for k in ("Close", "High", "Low", "Volume"))
    ma = w["Close"].rolling(R["ma_weeks"]).mean().values
    i = n - 1
    sc, slope = slope_class(ma, i, R)
    above = c[i] > ma[i]
    rs = mansfield(w["Close"], bench_w, R).values if bench_w is not None else np.full(n, np.nan)
    rs_now = rs[i]
    rs_prev = rs[i - R["rs_rising_w"]] if i >= R["rs_rising_w"] else np.nan
    rs_up = bool(rs_now > rs_prev) if not (np.isnan(rs_now) or np.isnan(rs_prev)) else None
    k = R["pivot_w"]
    ph = [j for j in pivots(h, k, True) if j >= n - 52]
    pl = [j for j in pivots(l, k, False) if j >= n - 52]
    hh = bool(h[ph[-1]] > h[ph[-2]]) if len(ph) >= 2 else None
    hl = bool(l[pl[-1]] > l[pl[-2]]) if len(pl) >= 2 else None
    # prior trend for a flat MA
    prior = None
    for j in range(i - 1, max(R["ma_weeks"] + R["slope_lookback_w"] - 2, i - R["prior_trend_w"]), -1):
        s2, _ = slope_class(ma, j, R)
        if s2 in ("up", "down"):
            prior = s2
            break
    hi52, lo52 = h[-52:].max(), l[-52:].min()
    if prior is None:
        prior = "down" if c[i] < (hi52 + lo52) / 2 else "up"
    flat_run = 0
    for j in range(i, -1, -1):
        s2, _ = slope_class(ma, j, R)
        if s2 == "flat":
            flat_run += 1
        else:
            break
    crosses13 = int(np.sum(np.diff(np.sign(c[-14:] - ma[-14:])) != 0))
    vol10, vol52 = v[-10:].mean(), v[-52:].mean()
    new_high_10 = bool(h[-10:].max() >= hi52)
    bo = find_breakout(w, ma, R)
    bo_ok = None
    if bo:
        bo["holding"] = bool(c[i] >= bo["level"] and above)
        bo["vol_ok"] = bool(bo["vol_ratio"] is not None and bo["vol_ratio"] >= R["vol_mult"])
        bo["pct_above"] = _f((c[i] / bo["level"] - 1) * 100, 1)
        bo_ok = bo["holding"] and bo["vol_ok"]

    sp = stage_path(w, ma, R)
    stage = sp["stage"] or (2 if sc == "up" else 4 if sc == "down" else 1 if prior == "down" else 3)
    if bo_ok and stage != 2:
        bo_ok = False  # broke a 26-week high but is still inside the bigger base range -> not a stage-2 breakout yet
        bo["in_range"] = True
    if stage == 2:
        sub = "2A" if bo_ok else ("2-ext" if (c[i] / ma[i] - 1) * 100 > R["extended_pct"] else "2" if above else "2-weak")
    elif stage == 4:
        sub = "4" if not above else "4-late"
    elif stage == 1:
        sub = "1B" if sp["since_w"] >= R["min_base_w"] else "1A"
    else:
        sub = "3"
    def ck(key, ok, he):
        return {"k": key, "ok": None if ok is None else bool(ok), "he": he}
    checks = {
        1: [ck("ma_flat", sc == "flat", "30W SMA שטוח (שינוי ≤1% ב-5 שבועות)"),
            ck("base10", flat_run >= R["min_base_w"], f"בסיס בוגר: ממוצע שטוח {flat_run} שבועות (≥10)"),
            ck("cross", crosses13 >= 1, f"המחיר חוצה את הממוצע הלוך ושוב ({crosses13} חציות ב-13 שבועות)"),
            ck("dry", vol10 < vol52, "מחזור מתייבש: ממוצע 10 שבועות < ממוצע 52 שבועות")],
        2: [ck("above", above, "סגירה מעל 30W SMA"),
            ck("ma_up", sc == "up" or (bo_ok and sc == "flat"), "30W SMA עולה (בפריצה: שטוח-עולה)"),
            ck("hhhl", (hh and hl) if hh is not None and hl is not None else None, "שיאים עולים ושפלים עולים (52 שבועות)"),
            ck("rs", (rs_now > 0 and rs_up) if rs_up is not None else None, "Mansfield RS > 0 ועולה")],
        3: [ck("ma_flat", sc == "flat", "30W SMA שטוח אחרי עלייה"),
            ck("whipsaw", crosses13 >= 2, f"חציות של הממוצע הלוך ושוב ({crosses13} ב-13 שבועות, ≥2)"),
            ck("churn", vol10 > vol52 and not new_high_10, "מחזור גבוה (10ש > 52ש) בלי שיא 52 שבועות חדש"),
            ck("rs_weak", (not rs_up) if rs_up is not None else None, "Mansfield RS נחלש (יורד ב-4 שבועות)")],
        4: [ck("below", not above, "סגירה מתחת ל-30W SMA"),
            ck("ma_down", sc == "down", "30W SMA יורד (שינוי < -1% ב-5 שבועות)"),
            ck("lhll", ((hh is False) and (hl is False)) if hh is not None and hl is not None else None, "שיאים יורדים ושפלים יורדים"),
            ck("rs_neg", (rs_now < 0 and rs_up is False) if rs_up is not None else None, "Mansfield RS < 0 ויורד")],
    }[stage]
    score = sum(1 for x in checks if x["ok"])
    out = {
        "stage": stage, "sub": sub, "score": score, "conf": "high" if score == 4 else "med" if score == 3 else "low",
        "checks": checks, "week": w.index[i].strftime("%Y-%m-%d"), "close": _f(c[i]), "ma30": _f(ma[i]),
        "slope": _f(slope), "slope_cls": sc, "pct_ma": _f((c[i] / ma[i] - 1) * 100, 1), "rs": _f(rs_now, 1),
        "rs_prev": _f(rs_prev, 1), "rs_up": rs_up, "hh": hh, "hl": hl, "prior": prior, "flat_w": flat_run,
        "crosses13": crosses13, "hi52": _f(hi52), "pct_hi52": _f((c[i] / hi52 - 1) * 100, 1),
        "at_hi52": bool(c[i] >= hi52 * 0.97), "weeks": n, "bo": None,
        "range": {"ceil": _f(sp["ceil"]), "floor": _f(sp["floor"]), "since_w": sp["since_w"],
                  "since": w.index[sp["start"]].strftime("%Y-%m-%d") if sp["stage"] else None},
    }
    if bo:
        out["bo"] = {k2: (_f(v2) if isinstance(v2, float) else v2) for k2, v2 in bo.items() if k2 != "idx"}
    # trade plan (Eyal 2026-11-14): the entry is ALWAYS a Buy-Stop slightly above the base resistance -- 2A = that level
    # just broke (buy only while still in the buy zone, else don't chase); stage 1 / stage-2 continuation base = the order
    # waits above the ceiling. R:R from that Buy-Stop entry to the nearest overhead resistance (2 years).
    out["pct_above_ma_lim"] = bool((c[i] / ma[i] - 1) * 100 > R["max_pct_above_ma"])
    if bo_ok:
        p = trade_levels(w, ma[i], buy_stop_price(bo["level"], R), bo["level"], bo["base_low"], R)
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
            p = trade_levels(w, ma[i], buy_stop_price(bn["top"], R), bn["top"], bn["low"], R)
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
        # don't chase: price (or the Buy-Stop) too far above the breakout level / the 30W SMA
        far = max(c[i], p["entry"])
        p["chase"] = bool((far / lvl - 1) * 100 > R["buy_zone_pct"] or (far / ma[i] - 1) * 100 > R["max_pct_above_ma"])
    return out


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
def prefilter(u: Dict[str, Any], weeks: int, close: float, dollar_vol_m: Optional[float], R=RULES) -> List[Dict[str, Any]]:
    inst = u.get("inst_own")
    small_bio = (u.get("industry") == "Biotechnology") and (u.get("mcap") or 0) < R["biotech_cap_b"] * 1e9
    wk_vol = (u.get("avg_vol") or 0) * 5
    return [
        {"k": "price", "ok": close >= R["min_price"], "he": f"מחיר ≥ ${R['min_price']:.0f} (מינימום קשיח $10 בסריקה)"},
        {"k": "liq", "ok": bool((dollar_vol_m or 0) >= R["min_dollar_vol_m"] or wk_vol >= R["min_week_vol"]),
         "he": "נזילות: מחזור יומי > $30M או > 500K מניות בשבוע"},
        {"k": "inst", "ok": None if inst is None else bool(R["inst_lo"] <= inst <= R["inst_hi"]), "he": "החזקה מוסדית 25%–85%"},
        {"k": "bio", "ok": not small_bio, "he": "לא ביוטק קטן (ביוטכנולוגיה מתחת ל-$2B שווי)"},
        {"k": "hist", "ok": weeks >= R["min_weeks"], "he": "לפחות 40 שבועות מסחר"},
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
    etfs = sorted(set(MARKET) | set(SECTOR_ETF.values()) | set(INDUSTRY_ETF.values()) | {BENCH})
    hm = load_history(tickers + etfs, offline)
    last = ss.last_us_session_date()
    bw = weekly(hm[BENCH], last)["Close"] if BENCH in hm else None

    etf_out = {}
    for e in etfs:
        if e == BENCH or e not in hm:
            continue
        r = classify(weekly(hm[e], last), bw, R)
        if r:
            etf_out[e] = {"name": ETF_NAMES.get(e, e), **{k: r[k] for k in ("stage", "sub", "score", "conf", "close", "ma30", "slope", "pct_ma", "rs", "rs_up", "week", "checks")}}
    strong = sorted([e for e in SECTOR_ETF.values() if e in etf_out and etf_out[e]["stage"] == 2 and (etf_out[e]["rs"] or -99) > 0],
                    key=lambda e: -(etf_out[e]["rs"] or 0))[:3]
    mkt_stage4 = etf_out.get("SPY", {}).get("stage") == 4

    rows, sparks, skipped = [], {}, {"no_history": 0, "short_history": 0}
    OUT_CANDLES.mkdir(parents=True, exist_ok=True)
    for t in tickers:
        u = U[t]
        df = hm.get(t)
        if df is None or getattr(df, "empty", True):
            skipped["no_history"] += 1
            continue
        w = weekly(df, last)
        r = classify(w, bw, R)
        if r is None:
            skipped["short_history"] += 1
            continue
        d = df.copy(); d.index = pd.to_datetime(d.index)
        dv = float((d["Close"] * d["Volume"]).iloc[-30:].mean() / 1e6) if len(d) else None
        etf = INDUSTRY_ETF.get(u.get("industry")) or SECTOR_ETF.get(u.get("sector"))
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
                {"k": "mkt", "ok": not mkt_stage4, "he": f"שוק כללי (SPY) לא בשלב 4 (כעת שלב {etf_out.get('SPY', {}).get('stage', '?')})"},
                {"k": "sector", "ok": None if not e else bool(e["stage"] == 2 and (e["rs"] or 0) > 0),
                 "he": f"סקטור {etf or '?'} בשלב 2 עם RS > 0" + (f" (שלב {e['stage']}, RS {e['rs']})" if e else "")},
                {"k": "rs", "ok": rs_ok, "he": "Mansfield RS > 0 ועולה"},
                {"k": "chase", "ok": not p["chase"],
                 "he": f"לא רודפים: עד {R['buy_zone_pct']:g}% מעל רמת הפריצה ועד {R['max_pct_above_ma']:g}% מעל 30W SMA "
                       f"(סגירה {p['close_vs_level']:+}% מהרמה, {r['pct_ma']:+}% מהממוצע; Buy-Stop {p['entry_vs_ma']:+}% מהממוצע)"
                       + (" — רחוקה מדי / אל תרדוף" if p["chase"] else "")},
                {"k": "stop", "ok": not p["stop_wide"], "info": True, "he": f"מידע בלבד (לא פוסל): SL עד {R['max_stop_pct']:g}% מתחת לכניסה ({p['risk_pct']}%, לפי {'שפל תקף' if p['stop_basis'] == 'low' else '30W SMA'})"
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
                     "he": f"המחיר מעל 30W SMA שאינו יורד (שיפוע {r['slope_cls']})"},
                ]
        # 'info' checks (SL width, Eyal 2026-11-14 'don't disqualify for a wide stop') are shown but never gate
        bs = entry_pass(entry, pre)
        rows.append({
            "t": t, "n": u.get("company"), "ex": u.get("exchange"), "sec": u.get("sector"), "ind": u.get("industry"),
            "etf": etf, "etf_stage": e["stage"] if e else None, "etf_rs": e["rs"] if e else None,
            "mcap_b": _f((u.get("mcap") or 0) / 1e9, 1) if u.get("mcap") else None, "inst": u.get("inst_own"),
            "dv_m": _f(dv, 1), "earn": earn, "earn_td": td, **r, "pre": [{"k": x["k"], "ok": x["ok"]} for x in pre], "pre_ok": all(x["ok"] is not False for x in pre),
            "earn_eff": ei["eff"], "earn_timing": timing, "earn_live_week": in_live, "earn_est": ei["est"],
            "earn_last": ei["last"], "earn_last_ago": ei["last_ago"],
            "earn_block": bool(earn and td is not None and td <= R["earn_td"]),
            "post_earn": next((x["he"] for x in entry if x["k"] == "post"), None),
            "post_gap": bool(next((x for x in entry if x["k"] == "post" and x["ok"] is False), None)),
            "entry": entry, "entry_ok": bs, "bs": bs,
        })
        sparks[t] = spark(w, R["spark_weeks"])
        wc = w.iloc[-R["candle_weeks"]:]
        cj = json.dumps({"w": [[ix.strftime("%Y-%m-%d"), *(round(float(x), 2) for x in row[:4]), int(row[4])]
                               for ix, row in zip(wc.index, wc[["Open", "High", "Low", "Close", "Volume"]].values)]},
                        separators=(",", ":"))
        cp = OUT_CANDLES / f"{t}.json"
        if not cp.exists() or cp.read_text() != cj:
            cp.write_text(cj)
    for e in etf_out:
        if e in hm:
            sparks[e] = spark(weekly(hm[e], last), R["spark_weeks"])
    counts = {str(s): sum(1 for x in rows if x["stage"] == s) for s in (1, 2, 3, 4)}
    counts["2A"] = sum(1 for x in rows if x["sub"] == "2A")
    cands = sorted((x for x in rows if x["bs"]), key=lambda x: -(x["plan"]["rr"] or 0))
    counts["bs"] = len(cands)
    doc = {
        "version": 1, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "week": max((x["week"] for x in rows), default=None), "rules": R, "screens": SCREENS,
        "finviz_totals": uni.get("totals"), "finviz_fetched_at": uni.get("fetched_at"), "skipped": skipped,
        "market": {k: etf_out[k] for k in MARKET if k in etf_out},
        "sectors": {k: etf_out[k] for k in etf_out if k not in MARKET}, "strong_sectors": strong,
        "pre_he": {x["k"]: x["he"] for x in prefilter({}, 0, 0.0, None, R)},  # row 'pre' = [{k, ok}] (text once here)
        "counts": counts, "rows": rows,
        "buy_stop_candidates": [candidate(x) for x in cands],
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    OUT_SPARK.write_text(json.dumps(sparks, separators=(",", ":")))
    print(f"[stages] {len(rows)} stocks, counts {counts}, skipped {skipped} -> {OUT} ({OUT.stat().st_size // 1024} KB), "
          f"{OUT_SPARK.name} ({OUT_SPARK.stat().st_size // 1024} KB)")
    return doc


def candidate(x: Dict[str, Any]) -> Dict[str, Any]:
    p = x["plan"]
    return {"t": x["t"], "n": x["n"], "kind": p["kind"], "sub": x["sub"], "close": x["close"], "level": p["level"],
            "buy_stop": p["entry"], "stop": p["stop"], "stop_pct": p["risk_pct"], "target": p["target"],
            "target_src": p["target_src"], "open_sky": p["open_sky"], "rr": p["rr"], "shares": p["shares"],
            "pos_usd": p["pos_usd"], "vol_need": p.get("vol_need"), "earn": x["earn"], "earn_td": x["earn_td"],
            "earn_est": x.get("earn_est", False), "post_earn": x.get("post_earn"), "ex": x["ex"]}


KIND_HE = {"breakout": "פריצה טרייה (באזור קנייה)", "trigger": "בסיס שלב 1 מתחת לתקרה", "continuation": "בסיס המשך בשלב 2"}


def alert_text(doc: Dict[str, Any]) -> Optional[str]:
    """Hebrew Telegram text for the Buy-Stop candidates (None = nothing actionable -> no message)."""
    cs = doc.get("buy_stop_candidates") or []
    if not cs:
        return None
    R = doc["rules"]
    lines = [f"🟢 שיטת סטף — מועמדות ל-Buy-Stop (שבוע {doc['week']}): {len(cs)}", ""]
    for c in cs:
        tgt = f"${c['target']}" + (" (שמיים פתוחים · R:R 2.5)" if c["open_sky"] else " (התנגדות תקורה)")
        lines += [f"{c['t']} · {KIND_HE.get(c['kind'], c['kind'])}",
                  f"Buy-Stop ${c['buy_stop']} · סטופ ${c['stop']} ({c['stop_pct']}%) · יעד {tgt}",
                  f"R:R 1:{c['rr']} · {c['shares']} מניות לסיכון ${R['risk_usd']:g} (${c['pos_usd']}) · דוח {(c['earn'] + (' (משוער)' if c.get('earn_est') else '') + (f" — בעוד {c['earn_td']} ימ״ס" if c.get('earn_td') is not None else '')) if c['earn'] else 'לא ידוע'}"]
        if c.get("post_earn"):
            lines.append(c["post_earn"])
        if c["kind"] != "breakout" and c.get("vol_need"):
            lines.append(f"תנאי: מחזור שבוע הפריצה ≥ {R['vol_mult']:g}x ממוצע 10 ש׳ (≥ {int(c['vol_need']):,} מניות) — אחרת פריצת שווא")
        lines.append("")
    lines.append("בלי פקודות אוטומטיות — רק התראה. https://retest-scanner.vercel.app/#/stages")
    return "\n".join(lines)


TG_CHAT_FILE = Path("/workspace/cache/telegram_chat_id")


def send_alert(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Telegram (same bot + chat as the retest price alerts). Token from env TELEGRAM_BOT_TOKEN (never printed); chat id
    from env TELEGRAM_CHAT_ID or /workspace/cache/telegram_chat_id. Sends only when there is a candidate."""
    import os
    import requests
    text = alert_text(doc)
    if not text:
        return {"sent": False, "why": "no candidates"}
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID") or (TG_CHAT_FILE.read_text().strip() if TG_CHAT_FILE.exists() else "")
    if not tok or not chat:
        return {"sent": False, "why": "missing TELEGRAM_BOT_TOKEN or chat id"}
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=30,
                      json={"chat_id": chat, "text": text, "disable_web_page_preview": True})
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return {"sent": bool(j.get("ok")), "message_id": (j.get("result") or {}).get("message_id"), "why": j.get("description"),
            "n": len(doc["buy_stop_candidates"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--alert", action="store_true", help="Telegram the Buy-Stop candidates (only when there are any)")
    a = ap.parse_args()
    sys.path.insert(0, str(REPO))
    doc = build(a.offline)
    print(f"[stages] Buy-Stop candidates: {len(doc['buy_stop_candidates'])} " + ", ".join(c["t"] for c in doc["buy_stop_candidates"]))
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
