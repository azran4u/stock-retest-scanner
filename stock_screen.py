#!/usr/bin/env python3
"""
FinViz screener pull + fast yfinance filters for weekly retest setups.
"""
from __future__ import annotations

import re
import time
import json
import warnings
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

SCREENER_URL = (
    "https://finviz.com/screener"
    "?v=111&f=geo_usa,sh_avgvol_o100,sh_instown_o80,sh_price_o10,"
    "ta_sma200_pa,ta_sma50_pb&ft=4&o=ticker"
)
DOLLAR_VOL_MIN = 50_000_000
AVG_VOL_DAYS = 30            # dollar vol = 30d avg volume × last close
MIN_WEEKLY_BARS = 150
SHORT_FLOAT_MAX = 0.05
RR_MIN = 2.0
EARNINGS_BLACKOUT_DAYS = 14
NEAR_ZONE_ATR = 1.0          # tighter: within ~1 ATR
MAX_EXT_ABOVE_ATR = 1.0      # close not more than 1 ATR above zone_hi
PULLBACK_TOUCH_ATR = 0.5     # post-breakout must tag zone (within 0.5 ATR)
FV_TTL_DAYS = 3              # FinViz quote fundamentals cache TTL
CACHE_DIR = Path("/workspace/cache")
OUT_CSV = Path("/workspace/stock_screen_results.csv")
OUT_TXT = Path("/workspace/stock_screen_results.txt")
OUT_VERIFY_CSV = Path("/workspace/stock_screen_verify.csv")
OUT_VERIFY_HTML = Path("/workspace/stock_screen_verify.html")
TICKERS_JSON = Path("/workspace/screener_tickers.json")
HIST_CACHE = Path("/workspace/hist_cache.pkl")
GROK_LIST = Path("/workspace/Grok.txt")  # optional EXCHANGE:TICKER hints
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

CACHE_DIR.mkdir(parents=True, exist_ok=True)
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def fetch_screener_tickers(max_pages: int = 30) -> List[str]:
    """Always scrape FinViz live — never reuse screener_tickers.json as input."""
    tickers: List[str] = []
    seen = set()
    for page in range(max_pages):
        r = 1 + page * 20
        url = SCREENER_URL + (f"&r={r}" if page > 0 else "")
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"[screener] page {page+1} error: {e}")
            break
        found = re.findall(r'data-boxover-ticker="([A-Z][A-Z0-9.\-]*)"', resp.text)
        new = []
        for t in found:
            if t not in seen:
                seen.add(t)
                new.append(t)
        print(f"[screener] page {page+1} (r={r}): {len(new)} new")
        if not new:
            break
        tickers.extend(new)
        time.sleep(0.45)
    # Snapshot only (audit / debugging) — never read back as cache
    TICKERS_JSON.write_text(json.dumps(tickers, indent=2))
    print(f"[screener] live fetch: {len(tickers)} tickers")
    return tickers


def _parse_pct_cell(td) -> Optional[float]:
    if td is None:
        return None
    b = td.find("b")
    raw = (b.get_text(strip=True) if b else td.get_text(strip=True) or "")
    raw = raw.replace("%", "").replace("-", "").strip()
    if not raw:
        return None
    try:
        return float(raw) / 100.0
    except ValueError:
        return None


def _finviz_label_value(soup: BeautifulSoup, label: str) -> Optional[float]:
    """Find FinViz snapshot cell by label text (link or div.snapshot-td-label)."""
    for a in soup.select("a"):
        if a.get_text(strip=True) == label:
            td = a.find_parent("td")
            if td and td.find_next_sibling("td"):
                return _parse_pct_cell(td.find_next_sibling("td"))
    for div in soup.select("div.snapshot-td-label"):
        if div.get_text(strip=True) == label:
            td = div.find_parent("td")
            if td and td.find_next_sibling("td"):
                return _parse_pct_cell(td.find_next_sibling("td"))
    return None


def scrape_finviz_fundamentals(ticker: str) -> Dict[str, Optional[float]]:
    """Short Float + Inst Own from FinViz quote; cached under cache/fv_{ticker}.json
    for FV_TTL_DAYS (default 3). Migrates legacy short_{ticker}.json when present.
    """
    cache_f = CACHE_DIR / f"fv_{ticker}.json"
    legacy = CACHE_DIR / f"short_{ticker}.json"
    cached: Dict[str, Any] = {}
    if cache_f.exists():
        try:
            cached = json.loads(cache_f.read_text())
        except Exception:
            cached = {}
    elif legacy.exists():
        try:
            cached = json.loads(legacy.read_text())
        except Exception:
            cached = {}

    short = cached.get("short_float")
    inst = cached.get("inst_own")
    fetched_at = cached.get("fetched_at")
    fresh = False
    if fetched_at and short is not None and inst is not None:
        try:
            ts = datetime.fromisoformat(str(fetched_at))
            age_days = (datetime.now(ts.tzinfo) - ts).total_seconds() / 86400.0 if getattr(ts, "tzinfo", None) else (datetime.utcnow() - ts).total_seconds() / 86400.0
            fresh = age_days < FV_TTL_DAYS
        except Exception:
            fresh = False
    if fresh:
        return {"short_float": short, "inst_own": inst}

    url = f"https://finviz.com/quote.ashx?t={ticker}&p=d"
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            out = {"short_float": short, "inst_own": inst, "fetched_at": fetched_at}
            cache_f.write_text(json.dumps(out))
            return {"short_float": short, "inst_own": inst}
        soup = BeautifulSoup(resp.text, "lxml")
        short = _finviz_label_value(soup, "Short Float")
        inst = _finviz_label_value(soup, "Inst Own")
        now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        out = {"short_float": short, "inst_own": inst, "fetched_at": now_iso}
        cache_f.write_text(json.dumps(out))
        legacy.write_text(json.dumps({"short_float": short, "fetched_at": now_iso}))
        time.sleep(0.25)
        return {"short_float": short, "inst_own": inst}
    except Exception as e:
        print(f"  [finviz scrape] {ticker}: {e}")
        out = {"short_float": short, "inst_own": inst}
        if fetched_at:
            out["fetched_at"] = fetched_at
        try:
            cache_f.write_text(json.dumps(out))
        except Exception:
            pass
        return {"short_float": short, "inst_own": inst}


def scrape_finviz_short_float(ticker: str) -> Optional[float]:
    return scrape_finviz_fundamentals(ticker).get("short_float")


def atr_series(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def find_swing_highs(highs: np.ndarray, left: int = 3, right: int = 3) -> List[int]:
    """Local maxima of `highs` (call with body tops for peaks; wick High only if needed)."""
    idxs = []
    for i in range(left, len(highs) - right):
        window = highs[i - left : i + right + 1]
        if highs[i] >= window.max() and np.argmax(window) == left:
            idxs.append(i)
    return idxs


def weekly_retest_setup(w: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    Heuristic weekly retest (v2, tighter):

    1) Swing / peak = local max of body top max(O,C) (3/3) — NOT wick High.
    2) Zone = [body_top=max(O,C), wick_high=H] of that peak candle.
    3) Breakout = first later weekly Close > zone_hi (and not on last 2 bars).
    4) Pullback REQUIRED: after breakout, some weekly Low <= zone_hi + 0.5*ATR
       (must actually tag the broken resistance).
    5) Current location: last close/low within 1*ATR of zone OR last 3 weeks
       touch zone; AND last close <= zone_hi + 1*ATR (not extended).
    6) Soft score: below-avg pullback volume vs breakout week; hammer /
       close>=zone_mid on latest week.
    7) Prefer most recent qualifying peak (then score/R:R).
    8) Geometry:
       entry = zone mid
       SL qualify: weeks whose body_top=max(O,C) OR High is inside [zone_lo, zone_hi];
            among those take lowest Low (deepest wick), SL just below that Low;
            clamp stop distance from entry to [0.5*ATR, 1.0*ATR]
            (widen if <0.5 ATR; cap if >1.0 ATR)
       TP = body_top of the latest (most recent) body-top swing AFTER breakout
       Require R:R >= 2.0
    """
    if len(w) < MIN_WEEKLY_BARS:
        return None

    w = w.copy().reset_index(drop=True)
    o = w["Open"].values.astype(float)
    h = w["High"].values.astype(float)
    l = w["Low"].values.astype(float)
    c = w["Close"].values.astype(float)
    v = w["Volume"].values.astype(float)
    bt = np.maximum(o, c)
    bb = np.minimum(o, c)

    atr = atr_series(w, 14).values
    atr_now = float(atr[-1]) if np.isfinite(atr[-1]) else np.nan
    if not np.isfinite(atr_now) or atr_now <= 0:
        return None

    last_i = len(w) - 1
    last_close = float(c[-1])
    last_low = float(l[-1])
    swings = find_swing_highs(bt, 3, 3)  # peaks by body top, not wick High
    if len(swings) < 2:
        return None

    candidates = []
    for si in swings:
        # peak must allow breakout + pullback history; within ~2y
        if si > last_i - 8 or si < last_i - 104:
            continue
        zone_lo = float(bt[si])
        zone_hi = float(h[si])
        if zone_hi <= zone_lo:
            zone_hi = zone_lo * 1.002
        zone_mid = (zone_lo + zone_hi) / 2.0

        bo_i = None
        for j in range(si + 1, last_i):
            if c[j] > zone_hi:
                bo_i = j
                break
        if bo_i is None or bo_i >= last_i - 1:
            continue

        # Must have actually pulled back to the zone after breakout
        pb_lows = l[bo_i + 1 : last_i + 1]
        if len(pb_lows) == 0:
            continue
        if float(pb_lows.min()) > zone_hi + PULLBACK_TOUCH_ATR * atr_now:
            continue

        def dist_to_zone(px: float) -> float:
            if zone_lo <= px <= zone_hi:
                return 0.0
            if px < zone_lo:
                return zone_lo - px
            return px - zone_hi

        d_close = dist_to_zone(last_close)
        d_low = dist_to_zone(last_low)
        near = min(d_close, d_low) <= NEAR_ZONE_ATR * atr_now
        touched = any(
            (l[k] <= zone_hi and h[k] >= zone_lo)
            for k in range(max(0, last_i - 2), last_i + 1)
        )
        if not (near or touched):
            continue
        # Not extended far above zone
        if last_close > zone_hi + MAX_EXT_ABOVE_ATR * atr_now:
            continue
        # Failed breakout deep below
        if last_close < zone_lo - 1.0 * atr_now:
            continue

        bo_vol = float(v[bo_i])
        pb_vols = v[bo_i + 1 :]
        pb_vol_avg = float(pb_vols.mean()) if len(pb_vols) else bo_vol
        vol_ok = pb_vol_avg < bo_vol * 1.05

        rng = float(h[-1] - l[-1])
        body = abs(float(c[-1] - o[-1]))
        lower_wick = float(bb[-1] - l[-1])
        hammer = rng > 0 and lower_wick >= body * 0.9 and c[-1] >= (l[-1] + 0.5 * rng)
        close_above_mid = last_close >= zone_mid
        bullish = hammer or close_above_mid or (c[-1] > o[-1] and touched)

        entry = zone_mid
        # body top OR wick top (High) inside zone
        mask = ((bt >= zone_lo) & (bt <= zone_hi)) | ((h >= zone_lo) & (h <= zone_hi))
        if not mask.any():
            continue
        wick_sl = float(l[mask].min()) - 0.01
        risk = entry - wick_sl
        if risk <= 0:
            continue
        min_risk = 0.5 * atr_now
        max_risk = 1.0 * atr_now
        atr_floor_applied = False
        atr_cap_applied = False
        if risk < min_risk:
            sl = entry - min_risk
            atr_floor_applied = True
        elif risk > max_risk:
            sl = entry - max_risk
            atr_cap_applied = True
        else:
            sl = wick_sl
        risk = entry - sl
        if risk <= 0:
            continue

        post_swings = [i for i in swings if i > bo_i]
        if post_swings:
            # latest = most recent chronologically
            tp = float(bt[max(post_swings)])
        else:
            if bo_i + 1 >= len(bt):
                continue
            # highest body top after breakout as proxy
            seg = bt[bo_i + 1 :]
            # exclude current incomplete if it's the only max far away — use max of segment
            tp = float(seg.max())
        if tp <= entry:
            continue
        rr = (tp - entry) / risk

        # Prefer more recent peaks
        recency = si / max(1, last_i)
        score = recency * 3.0
        if vol_ok:
            score += 2
        if bullish:
            score += 2
        if near:
            score += 1
        if touched:
            score += 1
        score += max(0.0, 2.0 - min(d_close, d_low) / atr_now)

        candidates.append({
            "pass_rr": rr >= RR_MIN,
            "rr": rr,
            "entry": entry,
            "sl": sl,
            "wick_sl": wick_sl,
            "atr_floor_applied": atr_floor_applied,
            "atr_cap_applied": atr_cap_applied,
            "tp": tp,
            "zone_lo": zone_lo,
            "zone_hi": zone_hi,
            "vol_ok": vol_ok,
            "bullish": bullish,
            "atr": atr_now,
            "score": score,
            "si": si,
            "reason": "PASS" if rr >= RR_MIN else f"R:R {rr:.2f} < {RR_MIN}",
        })

    if not candidates:
        return None
    # Prefer most recent peak among candidates; then score
    candidates.sort(key=lambda x: (-x["si"], -x["score"], -x["rr"]))
    best = candidates[0]
    # If best fails RR but another recent pass exists, take best pass by score among top-recency cluster
    passes = [x for x in candidates if x["pass_rr"]]
    if best["pass_rr"]:
        return best
    if passes:
        # only use a PASS if it's among the two most recent candidate peaks
        recent_sis = sorted({c["si"] for c in candidates}, reverse=True)[:2]
        recent_passes = [p for p in passes if p["si"] in recent_sis]
        if recent_passes:
            recent_passes.sort(key=lambda x: (-x["score"], -x["rr"]))
            return recent_passes[0]
    return best  # may be R:R fail


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    return d.resample("W-FRI").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()


def get_short_float(ticker: str) -> Tuple[Optional[float], str]:
    sf = scrape_finviz_short_float(ticker)
    if sf is not None:
        return sf, "finviz"
    return None, "N/A"


def get_fundamentals(ticker: str) -> Dict[str, Any]:
    data = scrape_finviz_fundamentals(ticker)
    short = data.get("short_float")
    inst = data.get("inst_own")
    return {
        "short_float": short,
        "short_src": "finviz" if short is not None else "N/A",
        "inst_own": inst,
        "inst_src": "finviz" if inst is not None else "N/A",
    }


def load_exchange_map() -> Dict[str, str]:
    """Best-effort US exchange map from Grok.txt lines like NASDAQ:ADI."""
    m: Dict[str, str] = {}
    if GROK_LIST.exists():
        for line in GROK_LIST.read_text().splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            ex, sym = line.split(":", 1)
            ex, sym = ex.strip().upper(), sym.strip().upper()
            if ex and sym:
                m[sym] = ex
                # also map MOG.A <-> MOG-A
                if "." in sym:
                    m[sym.replace(".", "-")] = ex
                if "-" in sym:
                    m[sym.replace("-", ".")] = ex
    return m


def tv_symbol_for(ticker: str, exchange_map: Optional[Dict[str, str]] = None) -> str:
    """TradingView chart URL. MOG-A -> MOG.A; best-effort NASDAQ/NYSE."""
    exchange_map = exchange_map or {}
    raw = ticker.strip().upper()
    tv_ticker = raw.replace("-", ".")
    ex = (
        exchange_map.get(raw)
        or exchange_map.get(tv_ticker)
        or "NASDAQ"
    )
    return f"https://www.tradingview.com/chart/?symbol={ex}:{tv_ticker}"


def process_from_daily(ticker: str, daily: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ticker": ticker, "status": "FAIL", "reason": "", "detail": {}}

    if daily is None or daily.empty:
        out["reason"] = "no price history"
        return out

    need = ["Open", "High", "Low", "Close", "Volume"]
    for col in need:
        if col not in daily.columns:
            out["reason"] = f"missing column {col}"
            return out

    hist = daily[need].dropna()
    if len(hist) < 50:
        out["reason"] = "too little daily history"
        return out

    last_close = float(hist["Close"].iloc[-1])
    avg_vol = float(hist["Volume"].tail(AVG_VOL_DAYS).mean())
    dollar_vol = last_close * avg_vol  # 30d avg vol × last close
    out["detail"]["price"] = last_close
    out["detail"]["current_price"] = last_close
    out["detail"]["avg_vol"] = avg_vol
    out["detail"]["avg_vol_30d"] = avg_vol
    out["detail"]["dollar_vol"] = dollar_vol
    out["detail"]["dollar_vol_30d"] = dollar_vol

    if dollar_vol < DOLLAR_VOL_MIN:
        out["reason"] = f"$vol(30d) ${dollar_vol/1e6:.1f}M < $50M"
        return out

    weekly = to_weekly(hist)
    out["detail"]["weekly_bars"] = len(weekly)
    if len(weekly) < MIN_WEEKLY_BARS:
        out["reason"] = f"history {len(weekly)} weekly bars < ~3y ({MIN_WEEKLY_BARS})"
        return out

    fund = get_fundamentals(ticker)
    short = fund["short_float"]
    short_src = fund["short_src"]
    short_flag = short is None
    out["detail"]["short_float"] = short
    out["detail"]["short_src"] = short_src
    out["detail"]["inst_own"] = fund.get("inst_own")
    out["detail"]["inst_src"] = fund.get("inst_src")
    if short_flag:
        out["detail"]["short_note"] = "short float N/A"
    elif short is not None and short >= SHORT_FLOAT_MAX:
        out["reason"] = f"short float {short*100:.2f}% >= 5%"
        return out

    setup = weekly_retest_setup(weekly)
    if setup is None:
        out["reason"] = "no weekly retest setup / geometry"
        if short_flag:
            out["reason"] += " | short float N/A"
        return out

    out["detail"].update({
        "entry": setup["entry"], "sl": setup["sl"], "tp": setup["tp"], "rr": setup["rr"],
        "zone_lo": setup["zone_lo"], "zone_hi": setup["zone_hi"], "atr": setup["atr"],
        "vol_ok": setup.get("vol_ok"), "bullish": setup.get("bullish"),
        "wick_sl": setup.get("wick_sl"),
        "atr_floor_applied": setup.get("atr_floor_applied"),
        "atr_cap_applied": setup.get("atr_cap_applied"),
    })

    if not setup["pass_rr"]:
        reason = f"R:R {setup['rr']:.2f} < {RR_MIN}"
        if short_flag:
            reason += " | short float N/A"
        out["reason"] = reason
        return out

    sf_str = f"{short*100:.2f}%" if short is not None else "N/A (flagged)"
    out["status"] = "PASS"
    out["reason"] = (
        f"PASS entry={setup['entry']:.2f} SL={setup['sl']:.2f} TP={setup['tp']:.2f} "
        f"R:R={setup['rr']:.2f} zone=[{setup['zone_lo']:.2f}-{setup['zone_hi']:.2f}] "
        f"short={sf_str} $vol=${dollar_vol/1e6:.1f}M"
    )
    if short_flag:
        out["reason"] += " | short float N/A flagged"
    return out


def _local_today() -> date:
    """Return today's calendar date in the user's Asia/Jerusalem timezone."""
    try:
        return datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    except Exception:
        # The box is configured to Asia/Jerusalem; keep a safe local fallback.
        return date.today()


def _date_only(value: Any) -> Optional[date]:
    """Convert a Yahoo date/timestamp to its calendar date without timezone drift."""
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def _calendar_earnings_dates(calendar: Any) -> List[date]:
    """Extract possible earnings dates from yfinance Ticker.calendar variants."""
    values: List[Any] = []
    if isinstance(calendar, dict):
        for key, value in calendar.items():
            if "earning" in str(key).lower() and "date" in str(key).lower():
                if isinstance(value, (list, tuple, set, pd.Series, np.ndarray)):
                    values.extend(list(value))
                else:
                    values.append(value)
    elif isinstance(calendar, pd.DataFrame):
        for col in calendar.columns:
            if "earning" in str(col).lower() and "date" in str(col).lower():
                values.extend(calendar[col].tolist())
        if not values and "earning" in str(calendar.index.name).lower():
            values.extend(calendar.index.tolist())
    elif isinstance(calendar, (list, tuple, set, pd.Series, np.ndarray)):
        values.extend(list(calendar))
    else:
        values.append(calendar)
    out = []
    for value in values:
        d = _date_only(value)
        if d is not None:
            out.append(d)
    return sorted(set(out))


def _earnings_dates_from_frame(frame: Any, today: date) -> List[date]:
    """Get future, not-yet-reported dates from get_earnings_dates output."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    candidates: List[date] = []
    # get_earnings_dates normally puts Earnings Date in the DatetimeIndex.
    for idx, row in frame.iterrows():
        d = _date_only(idx)
        if d is None:
            for col in frame.columns:
                if "earning" in str(col).lower() and "date" in str(col).lower():
                    d = _date_only(row.get(col))
                    if d is not None:
                        break
        if d is None or d < today:
            continue
        # A same-day row can already be reported; future rows are inherently
        # unreported, even when Yahoo omits EPS Estimate.
        reported = row.get("Reported EPS") if hasattr(row, "get") else None
        if d == today and reported is not None and not pd.isna(reported):
            continue
        candidates.append(d)
    return sorted(set(candidates))


def get_next_earnings(ticker: str, today: Optional[date] = None) -> Dict[str, Any]:
    """Fetch the next unreported earnings date through resilient yfinance APIs."""
    import yfinance as yf

    today = today or _local_today()
    errors: List[str] = []
    yf_ticker = yf.Ticker(ticker)

    # get_earnings_dates is the most useful source because it exposes the
    # reported EPS field; keep the other APIs as compatibility fallbacks.
    for method_name in ("get_earnings_dates",):
        method = getattr(yf_ticker, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                frame = method(limit=12)
            except TypeError:
                frame = method()
            dates = _earnings_dates_from_frame(frame, today)
            if dates:
                next_date = dates[0]
                return {
                    "days_to_earnings": int((next_date - today).days),
                    "earnings_known": True,
                    "earnings_blackout": 0 <= (next_date - today).days < EARNINGS_BLACKOUT_DAYS,
                    "earnings_source": method_name,
                }
        except Exception as exc:
            errors.append(f"{method_name}: {exc}")

    try:
        calendar = getattr(yf_ticker, "calendar", None)
        dates = [d for d in _calendar_earnings_dates(calendar) if d >= today]
        if dates:
            next_date = dates[0]
            days = int((next_date - today).days)
            return {
                "days_to_earnings": days,
                "earnings_known": True,
                "earnings_blackout": 0 <= days < EARNINGS_BLACKOUT_DAYS,
                "earnings_source": "calendar",
            }
    except Exception as exc:
        errors.append(f"calendar: {exc}")

    # Some yfinance releases expose earnings_dates as a property rather than
    # a callable method, so try it last.
    try:
        frame = getattr(yf_ticker, "earnings_dates", None)
        dates = _earnings_dates_from_frame(frame, today)
        if dates:
            next_date = dates[0]
            days = int((next_date - today).days)
            return {
                "days_to_earnings": days,
                "earnings_known": True,
                "earnings_blackout": 0 <= days < EARNINGS_BLACKOUT_DAYS,
                "earnings_source": "earnings_dates",
            }
    except Exception as exc:
        errors.append(f"earnings_dates: {exc}")

    return {
        "days_to_earnings": None,
        "earnings_known": False,
        "earnings_blackout": False,
        "earnings_source": "unknown",
        "earnings_error": "; ".join(errors[-2:]),
    }


def _enrich_verify_earnings(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Attach earnings metadata to every row eligible for verification output."""
    eligible = []
    for r in results:
        d = r.get("detail") or {}
        has_geom = d.get("entry") is not None and d.get("rr") is not None
        is_pass = r.get("status") == "PASS"
        is_rr_fail = has_geom and (not is_pass) and str(r.get("reason", "")).startswith("R:R")
        if is_pass or is_rr_fail:
            eligible.append(r["ticker"])

    today = _local_today()
    out: Dict[str, Dict[str, Any]] = {}
    for i, ticker in enumerate(eligible, start=1):
        try:
            info = get_next_earnings(ticker, today=today)
        except Exception as exc:
            info = {
                "days_to_earnings": None,
                "earnings_known": False,
                "earnings_blackout": False,
                "earnings_source": "unknown",
                "earnings_error": str(exc),
            }
        out[ticker] = info
        print(
            f"[earnings {i}/{len(eligible)}] {ticker}: "
            f"{info.get('days_to_earnings') if info.get('earnings_known') else 'unknown'}"
        )
    return out


def write_verify_outputs(results: List[Dict[str, Any]], exchange_map: Dict[str, str]) -> None:
    """CSV + static HTML for PASSes and geometric R:R fails, sorted by RR desc."""
    earnings_map = _enrich_verify_earnings(results)
    verify_rows = []
    for r in results:
        d = r.get("detail") or {}
        has_geom = d.get("entry") is not None and d.get("rr") is not None
        is_pass = r.get("status") == "PASS"
        is_rr_fail = has_geom and (not is_pass) and str(r.get("reason", "")).startswith("R:R")
        if not (is_pass or is_rr_fail):
            continue
        short = d.get("short_float")
        inst = d.get("inst_own")
        earnings = earnings_map.get(r["ticker"], {
            "days_to_earnings": None,
            "earnings_known": False,
            "earnings_blackout": False,
        })
        reason = r.get("reason", "")
        if not earnings.get("earnings_known"):
            reason += " | earnings unknown"
        elif earnings.get("earnings_blackout"):
            reason += f" | earnings blackout (<{EARNINGS_BLACKOUT_DAYS}d)"
        verify_rows.append({
            "ticker": r["ticker"],
            "status": r["status"],
            "current_price": d.get("current_price", d.get("price")),
            "entry": d.get("entry"),
            "sl": d.get("sl"),
            "tp": d.get("tp"),
            "rr": d.get("rr"),
            "zone_lo": d.get("zone_lo"),
            "zone_hi": d.get("zone_hi"),
            "atr": d.get("atr"),
            "short_float_pct": None if short is None else round(short * 100, 2),
            "inst_own_pct": None if inst is None else round(inst * 100, 2),
            "dollar_vol_30d": d.get("dollar_vol_30d", d.get("dollar_vol")),
            "avg_vol_30d": d.get("avg_vol_30d", d.get("avg_vol")),
            "weekly_bars": d.get("weekly_bars"),
            "days_to_earnings": earnings.get("days_to_earnings"),
            "earnings_known": bool(earnings.get("earnings_known")),
            "earnings_blackout": bool(earnings.get("earnings_blackout")),
            "tradingview_url": tv_symbol_for(r["ticker"], exchange_map),
            "reason": reason,
        })
    verify_rows.sort(key=lambda x: (-(x["rr"] if x["rr"] is not None else -1), x["ticker"]))
    vdf = pd.DataFrame(verify_rows)

    cols = [
        "ticker", "status", "current_price", "entry", "sl", "tp", "rr",
        "zone_lo", "zone_hi", "atr", "short_float_pct", "inst_own_pct",
        "dollar_vol_30d", "avg_vol_30d", "weekly_bars", "days_to_earnings",
        "earnings_known", "earnings_blackout", "tradingview_url", "reason",
    ]
    # ensure column order even if empty
    for c in cols:
        if c not in vdf.columns:
            vdf[c] = None
    vdf = vdf[cols]
    vdf.to_csv(OUT_VERIFY_CSV, index=False)

    def fmt_cell(col: str, val: Any) -> str:
        if val is None or (isinstance(val, float) and not np.isfinite(val)):
            return ""
        if col == "tradingview_url":
            return f'<a href="{val}" target="_blank" rel="noopener">{val}</a>'
        if col in ("current_price", "entry", "sl", "tp", "zone_lo", "zone_hi", "atr"):
            try:
                return f"{float(val):.4f}"
            except Exception:
                return str(val)
        if col == "rr":
            try:
                return f"{float(val):.3f}"
            except Exception:
                return str(val)
        if col == "days_to_earnings":
            try:
                return str(int(val))
            except Exception:
                return str(val)
        if col == "dollar_vol_30d":
            try:
                return f"{float(val):.0f}"
            except Exception:
                return str(val)
        if col == "avg_vol_30d":
            try:
                return f"{float(val):.0f}"
            except Exception:
                return str(val)
        return str(val)

    n_pass = sum(1 for x in verify_rows if x["status"] == "PASS")
    n_rr = sum(1 for x in verify_rows if x["status"] != "PASS")
    rows_html = []
    for row in verify_rows:
        cls = "pass" if row["status"] == "PASS" else "rrfail"
        tds = "".join(f"<td>{fmt_cell(c, row.get(c))}</td>" for c in cols)
        rows_html.append(f'<tr class="{cls}">{tds}</tr>')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Stock screen verify — sorted by R:R</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 16px; background: #0f1115; color: #e6e6e6; }}
h1 {{ font-size: 1.25rem; }}
.meta {{ color: #9aa0a6; margin-bottom: 12px; font-size: 0.9rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border: 1px solid #333; padding: 4px 6px; text-align: left; white-space: nowrap; }}
th {{ background: #1c2128; position: sticky; top: 0; cursor: default; }}
tr.pass {{ background: #132a1b; }}
tr.rrfail {{ background: #2a1a14; }}
tr:hover {{ outline: 1px solid #58a6ff; }}
a {{ color: #58a6ff; }}
.wrap {{ overflow-x: auto; }}
</style>
</head>
<body>
<h1>Stock screen verification table</h1>
<div class="meta">
Pre-sorted by <b>R:R descending</b>. Rows: PASS ({n_pass}) + R:R-fail with geometry ({n_rr}).
Dollar volume = <b>30-day average volume × last close</b>.
days_to_earnings is the integer calendar-day distance from <b>{_local_today().isoformat()} Asia/Jerusalem</b> to the next unreported Yahoo/yfinance earnings date; unknown values are flagged.
The 14-day blackout is marked by <b>earnings_blackout</b>; such names must be skipped from the PASS queue.
No hard-skips (e.g. AKTS); only real filters apply.
</div>
<div class="wrap">
<table>
<thead><tr>{''.join(f'<th>{c}</th>' for c in cols)}</tr></thead>
<tbody>
{chr(10).join(rows_html)}
</tbody>
</table>
</div>
</body>
</html>
"""
    OUT_VERIFY_HTML.write_text(html)
    print(f"Verify CSV: {OUT_VERIFY_CSV} ({len(verify_rows)} rows, {n_pass} PASS)")
    print(f"Verify HTML: {OUT_VERIFY_HTML}")


def format_line(res: Dict[str, Any]) -> str:

    if res["status"] == "PASS":
        return f"{res['ticker']} — {res['reason']}"
    return f"{res['ticker']} — FAIL: {res['reason']}"



def last_us_session_date(now=None) -> "pd.Timestamp":
    """Latest completed US cash-session calendar date (weekends -> Friday)."""
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        now = now or _dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = now or _dt.datetime.utcnow()
    d = now.date() if hasattr(now, "date") else now
    # Before ~10:00 ET Monday data for prior Friday may still be fine; for simplicity
    # use calendar weekday walk-back only.
    while d.weekday() >= 5:  # Sat/Sun
        d -= _dt.timedelta(days=1)
    return pd.Timestamp(d)


def download_batch(
    tickers: List[str],
    chunk: int = 50,
    start: Optional[str] = None,
    end: Optional[str] = None,
    period: str = "5y",
) -> Dict[str, pd.DataFrame]:
    """Download daily OHLCV. If start is set, fetch [start, end) instead of period."""
    import yfinance as yf
    out: Dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        print(f"[yf] download {i+1}-{i+len(batch)} / {len(tickers)} start={start} period={period if not start else '-'}")
        try:
            kwargs = dict(
                tickers=batch,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
            if start:
                kwargs["start"] = start
                if end:
                    kwargs["end"] = end
            else:
                kwargs["period"] = period
            data = yf.download(**kwargs)
        except Exception as e:
            print(f"[yf] batch error: {e}; per-ticker fallback")
            for t in batch:
                try:
                    tk = yf.Ticker(t)
                    if start:
                        h = tk.history(start=start, end=end, interval="1d", auto_adjust=True)
                    else:
                        h = tk.history(period=period, interval="1d", auto_adjust=True)
                    if h is not None and not h.empty:
                        out[t] = h
                except Exception as e2:
                    print(f"  {t}: {e2}")
            continue
        if len(batch) == 1:
            t = batch[0]
            out[t] = data[t].dropna(how="all") if isinstance(data.columns, pd.MultiIndex) else data.dropna(how="all")
        elif isinstance(data.columns, pd.MultiIndex):
            level0 = set(data.columns.get_level_values(0))
            for t in batch:
                if t in level0:
                    df = data[t].dropna(how="all")
                    if not df.empty:
                        out[t] = df
        time.sleep(0.35)
    return out


def _normalize_ohlcv_index(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    d = df.copy()
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    d = d[~d.index.duplicated(keep="last")].sort_index()
    return d


def refresh_hist_map(hist_map: Dict[str, pd.DataFrame], tickers: List[str]) -> Dict[str, pd.DataFrame]:
    """Fill missing tickers fully; for cached tickers, append bars after last date through latest US session."""
    target = last_us_session_date()
    missing: List[str] = []
    stale: List[Tuple[str, pd.Timestamp]] = []
    for t in tickers:
        df = hist_map.get(t)
        if df is None or getattr(df, "empty", True):
            missing.append(t)
            continue
        df = _normalize_ohlcv_index(df)
        hist_map[t] = df
        last = pd.Timestamp(df.index.max()).normalize()
        if last.date() < target.date():
            stale.append((t, last))

    if missing:
        print(f"Re-downloading {len(missing)} missing tickers (full history)...")
        extra = download_batch(missing, chunk=50)
        for t, df in extra.items():
            hist_map[t] = _normalize_ohlcv_index(df)

    if stale:
        print(f"Refreshing {len(stale)} stale tickers through {target.date()} (append missing days)...")
        # Group by start date to batch where possible
        by_start: Dict[str, List[str]] = {}
        start_for: Dict[str, pd.Timestamp] = {}
        for t, last in stale:
            start = (last + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            by_start.setdefault(start, []).append(t)
            start_for[t] = last
        end = (target + pd.Timedelta(days=1)).strftime("%Y-%m-%d")  # yfinance end exclusive-ish
        for start, group in by_start.items():
            print(f"  [{start} -> {end}] {len(group)} tickers")
            extra = download_batch(group, chunk=50, start=start, end=end)
            for t, new_df in extra.items():
                new_df = _normalize_ohlcv_index(new_df)
                if new_df is None or new_df.empty:
                    continue
                old = hist_map.get(t)
                if old is None or old.empty:
                    hist_map[t] = new_df
                else:
                    combined = pd.concat([old, new_df])
                    hist_map[t] = _normalize_ohlcv_index(combined)
    else:
        print(f"Cache fresh through {target.date()} for all present tickers")
    return hist_map


def main():
    print("=== Fetching FinViz screener tickers ===")
    tickers = fetch_screener_tickers()
    print(f"Total tickers: {len(tickers)}")

    if HIST_CACHE.exists():
        print(f"=== Loading cached history {HIST_CACHE} ===")
        hist_map = pd.read_pickle(HIST_CACHE)
    else:
        hist_map = {}
        print("=== No cache yet; will download full history ===")
    # Always fill missing tickers + append missing days for stale ones
    before = len(hist_map)
    hist_map = refresh_hist_map(hist_map, tickers)
    pd.to_pickle(hist_map, HIST_CACHE)
    print(f"Got history for {sum(1 for t in tickers if t in hist_map and hist_map[t] is not None and not getattr(hist_map[t], 'empty', True))} / {len(tickers)} (cache entries={len(hist_map)})")

    results, passes = [], []
    for i, ticker in enumerate(tickers):
        t0 = time.time()
        daily = hist_map.get(ticker)
        try:
            res = process_from_daily(ticker, daily if daily is not None else pd.DataFrame())
        except Exception as e:
            res = {"ticker": ticker, "status": "FAIL", "reason": f"exception: {e}", "detail": {}}
        print(f"[{i+1}/{len(tickers)}] {format_line(res)}  ({time.time()-t0:.2f}s)")
        results.append(res)
        if res["status"] == "PASS":
            passes.append(res)

    rows = []
    for r in results:
        d = r.get("detail") or {}
        rows.append({
            "ticker": r["ticker"], "status": r["status"], "reason": r["reason"],
            "price": d.get("price"), "dollar_vol": d.get("dollar_vol"),
            "dollar_vol_30d": d.get("dollar_vol_30d"), "avg_vol_30d": d.get("avg_vol_30d"),
            "weekly_bars": d.get("weekly_bars"), "short_float": d.get("short_float"),
            "inst_own": d.get("inst_own"),
            "entry": d.get("entry"), "sl": d.get("sl"), "tp": d.get("tp"), "rr": d.get("rr"),
            "zone_lo": d.get("zone_lo"), "zone_hi": d.get("zone_hi"), "atr": d.get("atr"),
        })
    pd.DataFrame(rows).to_csv(OUT_CSV, index=False)

    exchange_map = load_exchange_map()
    write_verify_outputs(results, exchange_map)

    first_pass = passes[0] if passes else None
    header = [
        "=" * 72,
        "STOCK SCREEN RESULTS (FinViz + yfinance weekly retest)",
        f"Tickers processed: {len(results)} | PASS: {len(passes)}",
    ]
    if first_pass:
        header += ["", "*** FIRST PASS WINNER ***", format_line(first_pass),
                   "*** (TradingView not touched) ***"]
    header += ["=" * 72, "", "--- Full list ---"]
    header += [format_line(r) for r in results]
    header += [
        "",
        "--- Heuristic limitations ---",
        (
            "v2 tighter retest: swing=3/3 local High max; zone=[body top, wick high]; "
            "breakout=first weekly close > zone_hi; MUST pull back to zone "
            "(post-BO low <= zone_hi+0.5 ATR); current price within ~1 ATR of zone "
            "and not >1 ATR above zone_hi. Soft score for quiet pullback volume + "
            "hammer/close>=mid. Prefer most-recent qualifying peak. "
            "entry=zone mid; SL=deepest Low among weeks with body-top OR High in zone, "
            "clamped to [0.5×ATR, 1×ATR]; "
            "TP=body top of latest post-breakout swing; R:R≥2 hard. Short% FinViz HTML "
            "cached; N/A flagged but continues. Not discretionary-chart identical. "
            "No ticker hard-skips — history/$vol/short/geometry only. Dollar vol = 30d avg volume × last close. Reports: historical-reports/."
        ),
    ]
    text = "\n".join(header)
    OUT_TXT.write_text(text)
    print("\n" + text)
    print(f"\nCSV: {OUT_CSV}\nTXT: {OUT_TXT}\nVERIFY_CSV: {OUT_VERIFY_CSV}\nVERIFY_HTML: {OUT_VERIFY_HTML}")


if __name__ == "__main__":
    main()
