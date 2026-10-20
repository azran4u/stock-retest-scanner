"""Primary weekly trend from confirmed swing highs / lows (pure, deterministic).

Pivot (fractal) definition, k = `pivot_k` bars each side, on weekly bars:
  swing high at i  : high[i] >  every high in the k bars before i  AND
                     high[i] >= every high in the k bars after i
  swing low  at i  : low[i]  <  every low in the k bars before i   AND
                     low[i]  <= every low in the k bars after i
  (a flat top/bottom is assigned to its first bar). A pivot is CONFIRMED once k bars exist after
  it, so the last k bars never hold a confirmed pivot: the current pullback may be unconfirmed.
Spacing: two same-kind pivots closer than `min_sep_weeks` are merged, keeping the more extreme
  one (the higher high / lower low; the earlier one on a tie).
Trend:
  up   = last two swing highs rising (H2 > H1) AND last two swing lows rising (L2 > L1)
  down = last two swing highs falling (H2 < H1) AND last two swing lows falling (L2 < L1)
  none = anything else (mixed, or fewer than 2 highs / 2 lows in the window)
Options (all explicit, see TREND_DEFAULTS):
  price               "wick" uses High/Low; "body" uses max/min(Open, Close)
  lookback_weeks      only bars in the last N weeks are searched for pivots
  provisional    if the highest high after the last confirmed swing high is above it
                      (a new high that is not confirmed yet, e.g. the current pullback started
                      < k weeks ago), it counts as the newest swing high. Mirror for downtrend.
  break_close         an uptrend is void (-> none) if the latest weekly close is below the last
                      swing low (mirror: downtrend void if close above the last swing high)
  pullback            how the current pullback (the bars after the newest swing high, for an
                      uptrend) is treated:
                        "judge"     its lowest low so far is the newest swing low, confirmed or
                                    not (L2), compared with the last swing low before the high (L1)
                        "ignore"    not judged: L1, L2 = the last two swing lows before the high
                        "confirmed" plain fractals: the last two confirmed swing lows, wherever
                      Mirror for a downtrend (the bounce after the newest swing low).
  min_step_atr        "clear" trend: H2 - H1 and L2 - L1 must each be >= this many weekly
                      ATR(atr_weeks) (0 = any rise counts)
  drop_incomplete / asof are applied by the caller via to_weekly(); trend() takes weekly bars.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# Defaults tuned 2026-10-20 on tests/golden_trend.yaml (tools/tune_trend.py, tools/cv_trend.py):
# accuracy 0.800 (104/130), balanced 0.794, leave-one-out 0.800. Plateau: pivot_k 3-4 with
# min_sep_weeks 10-13 all score 0.77-0.80; shorter spacing (4-8) drops to 0.66-0.73.
TREND_DEFAULTS: Dict[str, Any] = {
    "pivot_k": 3,
    "min_sep_weeks": 12,
    "price": "wick",
    "lookback_weeks": 104,
    "provisional": True,
    "break_close": True,
    "pullback": "ignore",
    "min_step_atr": 0.0,
    "atr_weeks": 14,
}

PULLBACK_MODES = ("judge", "ignore", "confirmed")


def find_pivots(values: np.ndarray, k: int, kind: str) -> List[int]:
    """Indices of confirmed fractal pivots in `values` ('high' -> maxima, 'low' -> minima)."""
    a = np.asarray(values, dtype=float)
    sign = 1.0 if kind == "high" else -1.0
    a = a * sign
    out = []
    for i in range(k, len(a) - k):
        left, right = a[i - k:i], a[i + 1:i + k + 1]
        if a[i] > left.max() and a[i] >= right.max():
            out.append(i)
    return out


def enforce_spacing(idx: List[int], values: np.ndarray, min_sep: int, kind: str) -> List[int]:
    """Merge same-kind pivots closer than min_sep bars, keeping the more extreme one."""
    if min_sep <= 1:
        return list(idx)
    out: List[int] = []
    for i in idx:
        if out and i - out[-1] < min_sep:
            j = out[-1]
            better = values[i] > values[j] if kind == "high" else values[i] < values[j]
            if better:
                out[-1] = i
        else:
            out.append(i)
    return out


def _swing(w: pd.DataFrame, i: int, v: np.ndarray, confirmed: bool = True) -> Dict[str, Any]:
    return {"date": w.index[i].strftime("%Y-%m-%d"), "price": round(float(v[i]), 4),
            "confirmed": confirmed}


def trend(weekly: pd.DataFrame, **params: Any) -> Dict[str, Any]:
    """{'trend': 'up'|'down'|'none', 'swing_highs': [...], 'swing_lows': [...], 'reason': str,
    'used': {'highs': [H1, H2], 'lows': [L1, L2]} (the 4 prices that decided it), 'params': {...}}.
    swing lists are oldest-first dicts {date, price, confirmed}; they hold the
    swings found in the lookback window (the last two of each decide the trend)."""
    unknown = set(params) - set(TREND_DEFAULTS)
    if unknown:
        raise TypeError(f"unknown trend params: {sorted(unknown)}")
    p = {**TREND_DEFAULTS, **params}
    k, sep = int(p["pivot_k"]), int(p["min_sep_weeks"])
    res: Dict[str, Any] = {"trend": "none", "swing_highs": [], "swing_lows": [], "used": None,
                           "reason": "", "params": p}
    w = weekly.tail(int(p["lookback_weeks"])) if p["lookback_weeks"] else weekly
    if len(w) < 2 * k + 2:
        res["reason"] = f"not enough weekly bars ({len(w)})"
        return res
    if p["price"] == "body":
        hi = np.maximum(w["Open"].values, w["Close"].values).astype(float)
        lo = np.minimum(w["Open"].values, w["Close"].values).astype(float)
    elif p["price"] == "wick":
        hi, lo = w["High"].values.astype(float), w["Low"].values.astype(float)
    else:
        raise ValueError("price must be 'wick' or 'body'")
    close = float(w["Close"].values[-1])
    ih = enforce_spacing(find_pivots(hi, k, "high"), hi, sep, "high")
    il = enforce_spacing(find_pivots(lo, k, "low"), lo, sep, "low")
    sh = [_swing(w, i, hi) for i in ih]
    sl = [_swing(w, i, lo) for i in il]

    if p["provisional"]:
        # newest unconfirmed extreme: a new high (low) after the last confirmed swing high (low)
        start = ih[-1] + 1 if ih else 0
        if start < len(hi):
            j = start + int(np.argmax(hi[start:]))
            if (not ih or hi[j] > hi[ih[-1]]) and j >= len(hi) - k:
                sh.append(_swing(w, j, hi, confirmed=False))
        start = il[-1] + 1 if il else 0
        if start < len(lo):
            j = start + int(np.argmin(lo[start:]))
            if (not il or lo[j] < lo[il[-1]]) and j >= len(lo) - k:
                sl.append(_swing(w, j, lo, confirmed=False))
    res["swing_highs"], res["swing_lows"] = sh, sl

    if len(sh) < 2 or len(sl) < 2:
        res["reason"] = f"need 2 swing highs and 2 swing lows, found {len(sh)} / {len(sl)}"
        return res
    mode = p["pullback"]
    if mode not in PULLBACK_MODES:
        raise ValueError(f"pullback must be one of {PULLBACK_MODES}")
    n = len(w)
    cl = w["Close"].values.astype(float)
    tr = np.maximum(hi_w := w["High"].values.astype(float), np.r_[cl[0], cl[:-1]]) - \
        np.minimum(w["Low"].values.astype(float), np.r_[cl[0], cl[:-1]])
    atr = float(np.mean(tr[-int(p["atr_weeks"]):]))
    step = float(p["min_step_atr"]) * atr

    def structure(top_sw, top_v, bot_sw, bot_idx, bot_v, up: bool):
        """(x1, x2) of the trend-defining side (highs for up) and (y1, y2) of the other side."""
        X = top_sw[-2:]
        if len(X) < 2:
            return None
        last_x = X[-1]["date"]
        prior = [s_ for s_ in bot_sw if s_["confirmed"] and s_["date"] < last_x]
        if mode == "confirmed":
            Y = [s_ for s_ in bot_sw if s_["confirmed"]][-2:]
            Y = (Y[0]["price"], Y[1]["price"]) if len(Y) == 2 else None
        elif mode == "ignore" or w.index[-1].strftime("%Y-%m-%d") == last_x:
            Y = (prior[-2]["price"], prior[-1]["price"]) if len(prior) >= 2 else None
        else:  # judge: the pullback extreme after the newest X is the newest Y
            ix = int(np.where(w.index.strftime("%Y-%m-%d") == last_x)[0][0])
            seg = bot_v[ix + 1:]
            ext = float(seg.min() if up else seg.max())
            Y = (prior[-1]["price"], round(ext, 4)) if prior else None
        if Y is None:
            return None
        return (X[0]["price"], X[1]["price"]), Y

    # uptrend: highs may include the unconfirmed newest high
    S = structure(sh, hi, sl, il, lo, up=True)
    if S is None:
        res["reason"] = "not enough swings (need 2 highs and 2 lows)"
        return res
    (h1, h2), (l1, l2) = S
    res["used"] = {"highs": [h1, h2], "lows": [l1, l2]}
    hh, hl = h2 - h1 > step if step else h2 > h1, l2 - l1 > step if step else l2 > l1
    up_desc = (f"highs {h1:g}->{h2:g} {'rising' if hh else 'not rising'}, "
               f"lows {l1:g}->{l2:g} {'rising' if hl else 'not rising'}"
               + (f" (step >= {step:.2f} = {p['min_step_atr']:g} ATR)" if step else ""))
    if hh and hl:
        if p["break_close"] and close < l2:
            res["reason"] = f"uptrend structure ({up_desc}) but close {close:g} < last swing low {l2:g}"
            return res
        res["trend"] = "up"
        res["reason"] = f"higher highs and higher lows: {up_desc}"
        return res
    D = structure(sl, lo, sh, ih, hi, up=False)
    if D is not None:
        (d1, d2), (u1, u2) = D
        ll = d1 - d2 > step if step else d2 < d1
        lh = u1 - u2 > step if step else u2 < u1
        if ll and lh:
            if p["break_close"] and close > u2:
                res["reason"] = f"downtrend structure but close {close:g} > last swing high {u2:g}; {up_desc}"
                return res
            res["trend"] = "down"
            res["used"] = {"highs": [u1, u2], "lows": [d1, d2]}
            res["reason"] = f"lower highs and lower lows: highs {u1:g}->{u2:g}, lows {d1:g}->{d2:g}"
            return res
    res["reason"] = f"mixed structure: {up_desc}"
    return res
