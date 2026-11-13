"""Stan Weinstein stage analysis page (#/stages, Eyal 2026-11-13).

Separate pipeline: its own FinViz screen, its own history cache, its own data file. It never touches the retest
screen, gates, expert zones, drawings or alerts.

Rules = Eyal's masterclass page (Weinstein, 'Secrets for Profiting in Bull and Bear Markets'): weekly (Friday) closes
only, 30-week SMA + its slope, breakout volume >= 2x the 10-week average, Mansfield RS vs the S&P 500 > 0 and rising,
top-down market (SPY / QQQ / IWM) + sector ETF stage, pre-filter (price, liquidity, inst own 25-85%, NYSE / NASDAQ,
no small biotech, >= 40 weeks, no heavy overhead within 20%), stop below the last structural low AND the 30W SMA,
R:R >= 3 to the first target, no new entry within 7 trading days of earnings. Every threshold is in RULES below and
is shown on the page.

  python -m srs_app.stages             # FinViz -> history -> stages -> app/data/stages.json + stages_spark.json
  python -m srs_app.stages --publish   # ... and upload the changed app data files (srs_app.publish_data)
  python -m srs_app.stages --offline   # recompute from the cached FinViz list + cached history (no network)
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
    "major_pivot_w": 4,          # overhead resistance / first target = MAJOR swing high (4 weekly bars on each side)
    "target_min_gap_pct": 2.0,   # first target = nearest major swing high > 2% above the entry
    "base_window_w": 26,         # breakout resistance = highest weekly high of the 26 weeks before the breakout week
    "min_base_w": 10,            # base: >= 10 consecutive weekly closes at / under that resistance (module 3: 10-16 weeks)
    "bo_max_weeks_ago": 3,       # breakout week = one of the last 4 completed weeks (0-3 weeks ago; entry window 1-3 weeks)
    "vol_avg_w": 10,             # breakout volume vs average weekly volume of the 10 weeks before it
    "vol_mult": 2.0,             # >= 2.0x  (< 1.5x = fakeout, avoid)
    "strong_close": 0.75,        # A+ breakout: close in the top 25% of the breakout week's range
    "buy_zone_pct": 10.0,        # 'in buy zone' = last close <= breakout level + 10% (else wait for a pullback)
    "extended_pct": 35.0,        # stage 2 'over-extended' = close > 35% above the 30W SMA (partial exit zone)
    "stop_buffer_pct": 1.0,      # stop = 1% under min(last swing low, 30W SMA)
    "entry_tick": 0.25,          # buy-stop trigger = resistance + $0.25
    "min_rr": 3.0,               # R:R to the first target >= 3
    "overhead_w": 78,            # overhead resistance = swing highs of the last 18 months ...
    "overhead_pct": 20.0,        # ... within 20% above the entry
    "earn_td": 7,                # no new entry within 7 trading days of earnings
    "min_price": 15.0, "hard_min_price": 10.0, "min_dollar_vol_m": 30.0, "min_week_vol": 500_000,
    "inst_lo": 25.0, "inst_hi": 85.0, "min_weeks": 40, "biotech_cap_b": 2.0,
    "risk_usd": 55.0, "account_usd": 5000.0, "position_cap_pct": 15.0,
    "spark_weeks": 104,
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


def find_breakout(w: pd.DataFrame, ma: np.ndarray, R=RULES) -> Optional[Dict[str, Any]]:
    """Earliest week b among the last bo_max_weeks_ago+1 completed weeks whose close broke above the base resistance
    (highest high of the base_window_w weeks before b) after >= min_base_w closes at / under it, with close > 30W SMA and
    the SMA not declining. Volume / holding are reported, not required here."""
    h, c, v = w["High"].values, w["Close"].values, w["Volume"].values
    n = len(w)
    for b in range(max(R["base_window_w"], n - 1 - R["bo_max_weeks_ago"]), n):
        res = h[b - R["base_window_w"]:b].max()
        if not (c[b] > res and c[b] > ma[b]):
            continue
        sc, _ = slope_class(ma, b, R)
        if sc not in ("up", "flat"):
            continue
        base = 0
        for j in range(b - 1, max(-1, b - 105), -1):
            if c[j] <= res:
                base += 1
            else:
                break
        if base < R["min_base_w"]:
            continue
        av = v[max(0, b - R["vol_avg_w"]):b].mean() if b > 0 else np.nan
        rng = h[b] - w["Low"].values[b]
        lo_base = w["Low"].values[b - min(base, R["base_window_w"]):b].min()
        return {"week": w.index[b].strftime("%Y-%m-%d"), "idx": b, "weeks_ago": n - 1 - b, "level": float(res),
                "base_weeks": base, "base_low": float(lo_base),
                "vol_ratio": float(v[b] / av) if av and av > 0 else None,
                "close_pos": float((c[b] - w["Low"].values[b]) / rng) if rng > 0 else None}
    return None


def trade_levels(w: pd.DataFrame, ma_now: float, entry: float, resistance: Optional[float], base_low: Optional[float],
                 R=RULES) -> Dict[str, Any]:
    """Stop below the last structural low AND the 30W SMA; first target = nearest weekly swing high above the entry
    (overhead resistance), else a measured move (resistance + base height)."""
    h, l = w["High"].values, w["Low"].values
    k = R["pivot_w"]
    pl = [i for i in pivots(l, k, False) if i >= len(w) - 26]
    swing_low = float(l[pl[-1]]) if pl else float(l[-10:].min())
    stop = min(swing_low, ma_now) * (1 - R["stop_buffer_pct"] / 100)
    ph = [i for i in pivots(h, R["major_pivot_w"], True) if i >= len(w) - R["overhead_w"]]  # last 18 months only
    above = sorted(float(h[i]) for i in ph if h[i] > entry * (1 + R["target_min_gap_pct"] / 100))
    target, tsrc = (above[0], "overhead") if above else (None, None)
    if target is None and resistance and base_low and resistance > base_low:
        target, tsrc = resistance + (resistance - base_low), "measured"
        if target <= entry * (1 + R["target_min_gap_pct"] / 100):
            target, tsrc = None, None
    risk = entry - stop
    rr = (target - entry) / risk if (target and risk > 0 and target > entry) else None
    recent = [float(h[i]) for i in ph if i >= len(w) - R["overhead_w"]]
    overhead = [x for x in recent if entry < x <= entry * (1 + R["overhead_pct"] / 100)]
    shares = int(R["risk_usd"] // risk) if risk > 0 else None
    return {"entry": _f(entry), "stop": _f(stop), "swing_low": _f(swing_low), "target": _f(target), "target_src": tsrc,
            "risk_pct": _f(risk / entry * 100, 1) if entry else None, "rr": _f(rr), "shares": shares,
            "pos_usd": _f(shares * entry, 0) if shares else None,
            "overhead": _f(min(overhead)) if overhead else None}


def trading_days_until(d: Optional[str], today: date) -> Optional[int]:
    if not d:
        return None
    dd = date.fromisoformat(d)
    if dd < today:
        return None
    return int(np.busday_count(today, dd))


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

    if bo_ok:
        stage, sub = 2, "2A"
    elif sc == "up" and above:
        stage = 2
        sub = "2-ext" if (c[i] / ma[i] - 1) * 100 > R["extended_pct"] else "2"
    elif sc == "down" and not above:
        stage, sub = 4, "4"
    elif sc == "flat":
        stage = 1 if prior == "down" else 3
        sub = ("1B" if flat_run >= R["min_base_w"] else "1A") if stage == 1 else "3"
    elif sc == "up":  # close under a rising MA
        stage, sub = 2, "2-weak"
    else:  # close above a declining MA
        stage, sub = 4, "4-late"

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
    }
    if bo:
        out["bo"] = {k2: (_f(v2) if isinstance(v2, float) else v2) for k2, v2 in bo.items() if k2 != "idx"}
    # trade plan: 2A = buy now / first pullback (entry = last close); stage 1 = buy-stop above the base top
    if bo_ok:
        out["plan"] = trade_levels(w, ma[i], float(c[i]), bo["level"], bo["base_low"], R)
        out["plan"]["kind"] = "breakout"
    elif stage == 1:
        win = min(max(flat_run, R["min_base_w"]), R["base_window_w"])
        top, blo = float(h[-win:].max()), float(l[-win:].min())
        out["base"] = {"top": _f(top), "low": _f(blo), "weeks": win, "dist_pct": _f((top / c[i] - 1) * 100, 1)}
        out["plan"] = trade_levels(w, ma[i], top + R["entry_tick"], top, blo, R)
        out["plan"]["kind"] = "trigger"
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
        earn = parse_earn(u.get("earn_raw", ""), today)
        state, cd = ss.earn_cache_lookup(t, today)  # the retest scanner's earnings cache, when it has a future date
        if cd and (not earn or date.fromisoformat(earn) < today):
            earn = cd.isoformat()
        td = trading_days_until(earn, today)
        pre = prefilter(u, len(w), r["close"], dv, R)
        e = etf_out.get(etf) if etf else None
        entry = []
        if r.get("plan"):
            p = r["plan"]
            entry = [
                {"k": "mkt", "ok": not mkt_stage4, "he": f"שוק כללי (SPY) לא בשלב 4 (כעת שלב {etf_out.get('SPY', {}).get('stage', '?')})"},
                {"k": "sector", "ok": None if not e else bool(e["stage"] == 2 and (e["rs"] or 0) > 0),
                 "he": f"סקטור {etf or '?'} בשלב 2 עם RS > 0" + (f" (שלב {e['stage']}, RS {e['rs']})" if e else "")},
                {"k": "rs", "ok": r["checks"][3]["ok"] if r["stage"] == 2 else (r["rs"] is not None and r["rs"] > 0 and bool(r["rs_up"])),
                 "he": "Mansfield RS > 0 ועולה"},
                {"k": "air", "ok": p["overhead"] is None, "he": "אוויר נקי: אין שיא סווינג מרכזי ב-20% שמעל הכניסה (18 חודשים)"
                 + (f" — יש ב-${p['overhead']}" if p["overhead"] else "")},
                {"k": "rr", "ok": None if p["rr"] is None else p["rr"] >= R["min_rr"], "he": "R:R ≥ 3 ליעד הראשון"},
                {"k": "earn", "ok": None if earn is None else not (td is not None and td <= R["earn_td"]),
                 "he": "אין דוח ב-7 ימי המסחר הקרובים" + (f" (דוח {earn})" if earn else " (תאריך דוח לא ידוע)")},
            ]
            if r["sub"] == "2A":
                bo = r["bo"]
                entry[2:2] = [
                    {"k": "vol", "ok": bo["vol_ok"], "he": f"מחזור הפריצה ≥ 2x ממוצע 10 שבועות ({bo['vol_ratio']}x)"},
                    {"k": "close", "ok": None if bo["close_pos"] is None else bo["close_pos"] >= R["strong_close"],
                     "he": "סגירה חזקה: נר הפריצה נסגר ב-25% העליונים של הטווח"},
                    {"k": "zone", "ok": (bo["pct_above"] or 0) <= R["buy_zone_pct"], "he": f"באזור קנייה: עד 10% מעל רמת הפריצה ({bo['pct_above']}%)"},
                ]
        rows.append({
            "t": t, "n": u.get("company"), "ex": u.get("exchange"), "sec": u.get("sector"), "ind": u.get("industry"),
            "etf": etf, "etf_stage": e["stage"] if e else None, "etf_rs": e["rs"] if e else None,
            "mcap_b": _f((u.get("mcap") or 0) / 1e9, 1) if u.get("mcap") else None, "inst": u.get("inst_own"),
            "dv_m": _f(dv, 1), "earn": earn, "earn_td": td, **r, "pre": [{"k": x["k"], "ok": x["ok"]} for x in pre], "pre_ok": all(x["ok"] is not False for x in pre),
            "entry": entry, "entry_ok": bool(entry) and all(x["ok"] is True for x in entry) and all(x["ok"] is not False for x in pre),
        })
        sparks[t] = spark(w, R["spark_weeks"])
    for e in etf_out:
        if e in hm:
            sparks[e] = spark(weekly(hm[e], last), R["spark_weeks"])
    counts = {str(s): sum(1 for x in rows if x["stage"] == s) for s in (1, 2, 3, 4)}
    counts["2A"] = sum(1 for x in rows if x["sub"] == "2A")
    doc = {
        "version": 1, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "week": max((x["week"] for x in rows), default=None), "rules": R, "screens": SCREENS,
        "finviz_totals": uni.get("totals"), "finviz_fetched_at": uni.get("fetched_at"), "skipped": skipped,
        "market": {k: etf_out[k] for k in MARKET if k in etf_out},
        "sectors": {k: etf_out[k] for k in etf_out if k not in MARKET}, "strong_sectors": strong,
        "pre_he": {x["k"]: x["he"] for x in prefilter({}, 0, 0.0, None, R)},  # row 'pre' = [{k, ok}] (text once here)
        "counts": counts, "rows": rows,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    OUT_SPARK.write_text(json.dumps(sparks, separators=(",", ":")))
    print(f"[stages] {len(rows)} stocks, counts {counts}, skipped {skipped} -> {OUT} ({OUT.stat().st_size // 1024} KB), "
          f"{OUT_SPARK.name} ({OUT_SPARK.stat().st_size // 1024} KB)")
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(REPO))
    build(a.offline)
    if a.publish:
        from srs_app.publish_data import publish
        r = publish(REPO / "app" / "data")
        print(json.dumps(r, ensure_ascii=False))
        if r.get("failed"):
            sys.exit(1)


if __name__ == "__main__":
    main()
