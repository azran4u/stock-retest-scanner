"""Fibonacci retracement anchor + daily SMAs for the app (Eyal 2026-10-24). Informational only, NOT a PASS gate.

Input everywhere = the app's daily candle rows [date, o, h, l, c, v] (export_data.export_candles, 5 years, prices rounded),
so Python (export) and TypeScript (webapp/src/indicators.ts, detail chart) see exactly the same numbers.

Weekly bars: Monday-Friday weeks (bar time = Monday, as toWeekly in the app); the current week may be partial.

Swing anchor (ZigZag on weekly bars, ATR threshold, same idea as TradingView's Auto Fib Retracement):
  ATR = Wilder ATR(14) of the weekly bars (value at each bar). Walking the bars, the swing direction flips when price
  moves against the running extreme by >= ZZ_ATR_MULT (3) x ATR:
    up-leg   : running extreme = highest high; a low <= extreme_high - 3 ATR confirms that high as a swing HIGH
    down-leg : running extreme = lowest low;   a high >= extreme_low + 3 ATR confirms that low as a swing LOW
  fib low  = the most recent CONFIRMED swing low (a weekly low followed by a >= 3 ATR rise)
  fib high = the highest high after it, up to the current bar (the leg's peak; its pullback need not be confirmed)
Levels (retracement, 0 at the high, 1 at the low, as a TradingView retracement drawn low -> high):
  price(x) = high - x * (high - low), x in 0, 0.382, 0.5, 0.618, 1 (0.382 / 0.5 / 0.618 = the key levels)
Confluence (key levels only):
  price : |current price - level| <= FIB_PRICE_TOL_ATR (0.25) x weekly ATR      -> 'המחיר ליד פיבו 0.5'
  zone  : level inside [zone_bottom - t, zone_top + t], t = FIB_ZONE_TOL_ATR (0.1) x weekly ATR -> 'מתלכד עם פיבו 0.5'
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

ZZ_ATR_MULT = 3.0
ATR_N = 14
FIB_LEVELS = (0.0, 0.382, 0.5, 0.618, 1.0)
FIB_KEY = (0.382, 0.5, 0.618)
FIB_PRICE_TOL_ATR = 0.25
FIB_ZONE_TOL_ATR = 0.1
SMA_PERIODS = (50, 100, 150, 200)


def _monday(d: str) -> str:
    t = date.fromisoformat(d[:10])
    return (t - timedelta(days=t.weekday())).isoformat()


def weekly_bars(daily: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Daily rows [date, o, h, l, c, (v)] -> Mon-Fri weekly bars {time (Monday), open, high, low, close,
    lo_date, hi_date (the daily dates of the week's low / high, first occurrence), last (last daily date)}."""
    out: List[Dict[str, Any]] = []
    for row in daily:
        d, o, h, l, c = str(row[0])[:10], float(row[1]), float(row[2]), float(row[3]), float(row[4])
        w = _monday(d)
        if not out or out[-1]["time"] != w:
            out.append({"time": w, "open": o, "high": h, "low": l, "close": c, "lo_date": d, "hi_date": d, "last": d})
            continue
        b = out[-1]
        if h > b["high"]:
            b["high"], b["hi_date"] = h, d
        if l < b["low"]:
            b["low"], b["lo_date"] = l, d
        b["close"], b["last"] = c, d
    return out


def wilder_atr_series(bars: Sequence[Dict[str, Any]], n: int = ATR_N) -> List[Optional[float]]:
    """Wilder ATR(n) at every bar (None until n true ranges exist); same recursion as data.ts atr()."""
    out: List[Optional[float]] = [None] * len(bars)
    a = 0.0
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        a = a + tr / n if i <= n else (a * (n - 1) + tr) / n
        if i >= n:
            out[i] = a
    return out


def zigzag_pivots(bars: Sequence[Dict[str, Any]], mult: float = ZZ_ATR_MULT, n: int = ATR_N) -> List[Dict[str, Any]]:
    """Confirmed swing pivots [{kind 'H'|'L', i, price}] (see module doc). Ties: the first bar of an equal extreme."""
    atr = wilder_atr_series(bars, n)
    H = [b["high"] for b in bars]
    L = [b["low"] for b in bars]
    argmax = lambda a, b: max(range(a, b + 1), key=lambda j: (H[j], -j))  # first highest high in [a, b]
    argmin = lambda a, b: min(range(a, b + 1), key=lambda j: (L[j], j))   # first lowest low in [a, b]
    piv: List[Dict[str, Any]] = []
    trend, hi_i, lo_i, ext = 0, 0, 0, 0
    for i in range(len(bars)):
        a = atr[i]
        if trend == 0:
            if H[i] > H[hi_i]:
                hi_i = i
            if L[i] < L[lo_i]:
                lo_i = i
            if a is None:
                continue
            up = lo_i < i and H[i] - L[lo_i] >= mult * a
            down = hi_i < i and H[hi_i] - L[i] >= mult * a
            if up and (not down or lo_i <= hi_i):
                piv.append({"kind": "L", "i": lo_i, "price": L[lo_i]})
                trend, ext = 1, argmax(lo_i + 1, i)
            elif down:
                piv.append({"kind": "H", "i": hi_i, "price": H[hi_i]})
                trend, ext = -1, argmin(hi_i + 1, i)
        elif trend == 1:
            if H[i] > H[ext]:
                ext = i
            elif a is not None and H[ext] - L[i] >= mult * a:
                piv.append({"kind": "H", "i": ext, "price": H[ext]})
                trend, ext = -1, argmin(ext + 1, i)
        else:
            if L[i] < L[ext]:
                ext = i
            elif a is not None and H[i] - L[ext] >= mult * a:
                piv.append({"kind": "L", "i": ext, "price": L[ext]})
                trend, ext = 1, argmax(ext + 1, i)
    return piv


def fib_anchor(daily: Sequence[Sequence[Any]], mult: float = ZZ_ATR_MULT) -> Optional[Dict[str, Any]]:
    """{low, low_date, high, high_date, atr_w, levels {x: price}} or None (no confirmed swing low / no rise after it)."""
    bars = weekly_bars(daily)
    if len(bars) < ATR_N + 2:
        return None
    piv = zigzag_pivots(bars, mult)
    lows = [p for p in piv if p["kind"] == "L"]
    if not lows:
        return None
    li = lows[-1]["i"]
    if li >= len(bars) - 1:
        return None
    hi = max(range(li + 1, len(bars)), key=lambda j: (bars[j]["high"], -j))
    lo_p, hi_p = bars[li]["low"], bars[hi]["high"]
    if hi_p <= lo_p:
        return None
    atr = wilder_atr_series(bars)[-1]
    return {"low": lo_p, "low_date": bars[li]["lo_date"], "high": hi_p, "high_date": bars[hi]["hi_date"],
            "atr_w": round(atr, 4) if atr else None, "levels": fib_levels(lo_p, hi_p)}


def fib_levels(low: float, high: float) -> Dict[str, float]:
    return {str(x): round(high - x * (high - low), 4) for x in FIB_LEVELS}


def fib_confluence(low: float, high: float, atr_w: Optional[float], price: Optional[float] = None,
                   zone_top: Optional[float] = None, zone_bottom: Optional[float] = None) -> Dict[str, Any]:
    """{'price_level': closest key level within the price tolerance (or None), 'zone_levels': key levels inside the zone}."""
    out: Dict[str, Any] = {"price_level": None, "zone_levels": []}
    if not atr_w or atr_w <= 0:
        return out
    lv = {x: high - x * (high - low) for x in FIB_KEY}
    if price is not None:
        near = [(abs(price - p), x) for x, p in lv.items() if abs(price - p) <= FIB_PRICE_TOL_ATR * atr_w]
        out["price_level"] = min(near)[1] if near else None
    if zone_top is not None and zone_bottom is not None:
        zt, zb = max(zone_top, zone_bottom), min(zone_top, zone_bottom)
        t = FIB_ZONE_TOL_ATR * atr_w
        out["zone_levels"] = [x for x, p in lv.items() if zb - t <= p <= zt + t]
    return out


def sma_weekly(daily: Sequence[Sequence[Any]], periods: Sequence[int] = SMA_PERIODS) -> Dict[int, List[Optional[float]]]:
    """Daily SMA(n) of closes, sampled at each week's last trading day -> one value per weekly bar (None = not enough days)."""
    closes = [float(r[4]) for r in daily]
    weeks = weekly_bars(daily)
    last_idx = []
    for i, r in enumerate(daily):
        if i + 1 == len(daily) or _monday(str(daily[i + 1][0])) != _monday(str(r[0])):
            last_idx.append(i)
    out: Dict[int, List[Optional[float]]] = {}
    pre = [0.0]
    for c in closes:
        pre.append(pre[-1] + c)
    for n in periods:
        out[n] = [((pre[i + 1] - pre[i + 1 - n]) / n) if i + 1 >= n else None for i in last_idx]
    assert len(last_idx) == len(weeks)
    return out
