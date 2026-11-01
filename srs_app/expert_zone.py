"""Expert zone ('אזור מומחים', Eyal 2026-11-01): a SECOND, independent support zone for the starred stocks, computed
by the textbook rules for the level a weekly retest comes back to. Informational overlay only: it never replaces,
edits or moves his / TV / bot zone and Long drawings, it is stored in its own file (app/data/expert_zones.json, NOT
the drawings table) and it does not count toward PASS, sizing, R:R or any filter.

Sources (research page 'חישוב הרמה: כללי המומחים מול הכלל שלנו'):
  level = the top of the base / the highest high of the pattern that was broken (Weinstein, Bulkowski; IBD: the last
  resistance / pivot before the breakout); a breakout is a weekly CLOSE above it (Weinstein; Murphy: Friday close).
  zone, not a line: from the highest wick (outer edge) down to the highest body of the bars that made the top
  (inner edge) (practitioner convention, LuxAlgo / getalphacharts), width sanity 0.25..0.5 weekly ATR.
  broken only on a weekly close more than 3% under the zone (Murphy: 3% for major levels; Weinstein: weekly close).

RULE (deterministic, weekly Mon-Fri bars built from the app's daily candles, only COMPLETED weeks for structure):
  A  = Wilder ATR(14) of the weekly bars at the last completed week (same as the app's ATR(W)).
  1. Breakout candidates, newest first, within the last LOOKBACK_W (156) weeks:
       week b is a breakout when close[b] > R  and  close[b-1] <= R, where
       R = max high of the BASE_W (26) weeks before b, made at week p (the base top, last occurrence if tied),
       and the top is at least MIN_BASE_GAP (2) weeks before b (at least one full week failed under it -> a base / handle,
       not a bar-after-bar run of new highs; IBD handles are 1-2 weeks).
  2. Zone of a candidate: top = R (the highest wick).
       cluster = weeks in [b-26, b-1] whose high >= top - 0.5 A (the bars that made the resistance)
       bottom  = the highest body top max(open, close) of the cluster
       width sanity: top - bottom < 0.25 A -> bottom = top - 0.25 A ('widened'); > 0.5 A -> top - 0.5 A ('clamped').
  3. A candidate is THE expert zone when (all of):
       moved away : the highest high from b on >= top + 1 A        (Edwards & Magee: price must move away first)
       not broken (completed weekly closes after b; tightened 2026-11-01, Eyal approved after KBWB):
                    (a) any close more than 3% under the bottom (< bottom x 0.97, Murphy 3%)       -> broken
                    (b) two CONSECUTIVE closes under the bottom (Murphy: two closes; Weinstein)    -> broken
                    (c) a single close under the bottom, not followed by a second -> still valid, flagged
                        'סגירה שבועית מתחת לאזור' with its date, and -10 points per such week (max -20)
                    the current (running) price more than 3% under the bottom also counts as broken
       pulled back toward it from above: last close <= post-breakout high - 1 A, and last close <= top + 2 A
       stage 2   : the 30-week SMA of weekly closes is not falling (now >= 4 weeks ago). A falling 30-week MA during
                   the pullback = stage 3/4, no longer a retest (Weinstein; research page 'ביטול וסימני כישלון').
                   Added 2026-11-01 for all stocks (crashes of 50%+ fell back to old bases far under the high).
  4. ACTIVE SUPPORT / HIGHER SHELF (v4, Eyal 2026-11-01 after STLD; Weinstein: trailing support under the latest higher
     low; O'Neil: base-on-base). For the valid candidate, after price first moved >= 1 A above the top:
       swing lows = completed weeks after the post-breakout high whose low <= the lows of the week before and after
                    (the last completed week has no week after it and is not a swing low yet)
       shelf      = >= 2 swing lows within 0.5 A of the lowest one (3+ lows preferred, then the highest, then the most
                    recent), its
                    lowest low L above the origin top + 0.5 A, and not broken by the same rules as the zone
                    (no close < L x 0.97 after its first low, no two consecutive closes < L, price not < L x 0.97)
       near       : when price is > 2 A above the origin top, the candidate is still valid if it is <= 2 A above the
                    shelf top (the shelf is the active support; STLD 10/30 at 250.8)
       zone       = bottom L, top = the lowest body bottom min(open, close) of the cluster weeks, width clamped to
                    0.25-0.5 A. The breakout level is kept as 'origin' (shown on the stock page).
       score on the shelf: time/volume from its first low on (volume vs the weeks since the breakout), touches = cluster
       size, retest = visits of the shelf, recency = weeks since its last low, round / confluence / below on the
       shelf; breakout quality and gap stay those of the original breakout. Trade re-derived on the shelf.
     The newest candidate that passes wins. None -> 'no expert level' with the reason of the newest candidate
     (no breakout in 3 years / broken / price too far above / never moved away / no pullback yet).

SIGNIFICANCE SCORE 0-100 (transparent: each factor's points, max, measured value and source):
  time      20  weeks of the base whose range overlaps the zone, 2.5 pts/week (Murphy: longer = stronger)
  touches   15  separate visits of the top (runs of cluster weeks): 1->4, 2->10, 3+->15 (StockCharts; Investopedia)
  volume    10  avg volume of the zone weeks / avg volume of the base: >=1.3 ->10, >=1.0 ->6, else 2
                (Murphy, Edwards & Magee: volume is the first criterion; Bulkowski found the opposite, weighted lightly)
  breakout  20  breakout-week volume / 10-week average: >=2 ->10 (Weinstein >=2x), >=1.5 ->6, >=1 ->3; close >= 1%
                above the top +5 (Murphy 1%); close in the upper half of the week's range +5
  retest    10  this is visit no. 1 ->10, 2 ->7, 3 ->3, 4+ ->0 (IBD: the 1st and 2nd pullbacks are the best)
  recency    5  weeks since the breakout <= 13 ->5, <= 26 ->3, <= 52 ->1 (Murphy; Bulkowski: age does not matter -> light)
  round      5  a round number (step by price) inside the zone +/- 0.1 A (Murphy; Bulkowski)
  gap        5  a daily gap up in the breakout week or the next one that starts at the zone (Murphy: breakaway gap = support)
  below    -20  penalty: -10 per single weekly close under the bottom since the breakout (rule (c) above)
  confluence 10 30-week SMA inside the zone +/- 0.5 A ->5 (Weinstein); Fib 0.382-0.618 of base low -> post-breakout
                high overlaps the zone ->5 (Murphy)

Which tickers: the CURRENT starred list (Supabase table watchlist). Python has no Supabase access, so the list comes
from /workspace/stock-screener/app_state.json, which the routine writes from SQL_WATCHLIST before the export (README
'App state'). The nightly export rebuilds the file for exactly that list (unstarred tickers drop out).

EXPERT TRADE (Eyal 2026-11-01 20:48; research page 'כניסה וסטופ' / 'אישור וטריגר באזור'), a separate overlay as well:
  entry = the zone top: buy when a week closes back above the top of the pattern (Bulkowski, Throwback entry: the best
          of the three entries tested, 89% wins / 10% stopped); 'confirmed' when the last weekly close is above it.
  SL    = under the retest low AND under the zone bottom: min(lowest low since the post-breakout high, bottom) - 0.1 ATR,
          moved under a round number sitting just above it (Murphy: stop beyond the round number, not on it);
          then at least 1 weekly ATR under the entry: sl = min(structural, entry - 1 A) (Eyal 2026-11-01; Bulkowski: tight
          stops get hit - < 4% about half the time within a month - normalized by volatility instead of a fixed 4%,
          which was ~1 ATR for a calm ETF and far inside the noise of a volatile stock); deeper than 8% is flagged (IBD: a leader rarely falls > 7-8% under the buy point).
  TP    = the high after the breakout, the pre-pullback high = the next resistance (IBD: enter before price returns to
          the high before the pullback); the measured move (top + base height, base height = top - base low) is shown
          as a secondary target only.  R:R = (TP - entry) / (entry - SL).

  python -m srs_app.expert_zone --all                          # nightly: every exported ticker + the starred list
  python -m srs_app.expert_zone --starred                      # whole file = the starred list in app_state.json
  python -m srs_app.expert_zone --add KNX                      # newly starred: compute KNX, keep the others
  python -m srs_app.expert_zone --remove KNX                   # unstarred: drop KNX now (the nightly would anyway)
  python -m srs_app.expert_zone --tickers ARM,BNY              # explicit list (replaces the file)
  python -m srs_app.expert_zone --refresh                      # recompute the tickers already in the file
A ticker without app candles yet (starred today, not exported) is downloaded in memory from yfinance (5y daily).
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RULE_VERSION = "expert-v4-2026-11-01"
LOOKBACK_W = 156
BASE_W = 26
MIN_BASE_GAP = 2
CLUSTER_ATR = 0.5
MIN_W_ATR, MAX_W_ATR = 0.25, 0.5
MOVE_AWAY_ATR = 1.0
BREAK_PCT = 0.03
PULLBACK_ATR = 1.0
NEAR_ATR = 2.0
ATR_N = 14

SRC = {
    "level": "Weinstein; Bulkowski; IBD (pivot = last resistance before the breakout)",
    "time": "Murphy: the longer price traded at a level, the stronger it is",
    "touches": "StockCharts / Investopedia: more separate tests = more significant (Bulkowski: not proven)",
    "volume": "Murphy; Edwards & Magee: volume at the level is the first criterion (Bulkowski disagrees)",
    "breakout": "Weinstein: breakout volume >= 2x average; Murphy: close >= 1% beyond the level",
    "retest": "IBD: the 1st and 2nd pullbacks to the pivot are the best, 3rd+ weaker",
    "recency": "Murphy: recent trading at the level = stronger (Bulkowski: age does not matter)",
    "round": "Murphy; Bulkowski: round numbers stop moves",
    "gap": "Murphy: a breakaway gap acts as support on the pullback",
    "confluence": "Weinstein: 30-week MA; Murphy: Fib 38-62% retracement",
    "trade_entry": "Bulkowski (Throwback entry): buy after a close back above the top of the pattern; 89% wins, 10% stopped",
    "trade_sl": "AlphaMethodX / Wyckoff: under the retest low and the level; Murphy: beyond a round number; at least 1 weekly ATR under the entry (Bulkowski: tight stops get hit, < 4% ~half the time; normalized by volatility); IBD: max ~7-8%",
    "trade_tp": "IBD: the high before the pullback (next resistance); measured move = base height added to the breakout (secondary)",
    "below": "Murphy: a close beyond the level weakens it (2 closes / 3% = broken); Weinstein: weekly close",
    "shelf": "Weinstein: trailing support under the latest higher low (stage 2); O'Neil: base-on-base",
}
LABEL_HE = {
    "time": "שבועות באזור", "touches": "נגיעות נפרדות", "volume": "נפח ברמה", "breakout": "איכות הפריצה",
    "retest": "מספר הבדיקה", "recency": "עדכניות", "round": "מספר עגול", "gap": "גאפ ברמה", "below": "סגירה מתחת לאזור", "confluence": "חפיפה (MA30 / פיבו)",
}


def _monday(d: str) -> str:
    t = date.fromisoformat(d[:10])
    return (t - timedelta(days=t.weekday())).isoformat()


def weekly(daily: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Daily rows [date, o, h, l, c, v] -> Mon-Fri weekly bars (time = Monday) with volume and the daily rows kept."""
    out: List[Dict[str, Any]] = []
    for r in daily:
        d, o, h, l, c = str(r[0])[:10], float(r[1]), float(r[2]), float(r[3]), float(r[4])
        v = float(r[5]) if len(r) > 5 and r[5] is not None else 0.0
        w = _monday(d)
        if not out or out[-1]["time"] != w:
            out.append({"time": w, "open": o, "high": h, "low": l, "close": c, "volume": v, "last": d, "days": [r]})
            continue
        b = out[-1]
        b["high"], b["low"], b["close"], b["last"] = max(b["high"], h), min(b["low"], l), c, d
        b["volume"] += v
        b["days"].append(r)
    return out


def wilder_atr(bars: Sequence[Dict[str, Any]], n: int = ATR_N) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    a = 0.0
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        a = a + tr / n if i <= n else (a * (n - 1) + tr) / n
    return a


def week_complete(last_daily: str, asof: Optional[str] = None) -> bool:
    """The last weekly bar is complete when its last session is a Friday, or `asof` is in a later week."""
    if asof and _monday(asof) > _monday(last_daily):
        return True
    return date.fromisoformat(last_daily[:10]).weekday() == 4


def round_step(p: float) -> float:
    return 1.0 if p < 25 else 5.0 if p < 100 else 10.0 if p < 500 else 50.0


def _runs(idx: Sequence[int]) -> int:
    n, prev = 0, None
    for i in idx:
        if prev is None or i != prev + 1:
            n += 1
        prev = i
    return n


def _zone_of(W: List[Dict[str, Any]], b: int, A: float) -> Dict[str, Any]:
    lo = max(0, b - BASE_W)
    R = max(W[k]["high"] for k in range(lo, b))
    p = max(k for k in range(lo, b) if W[k]["high"] == R)
    cluster = [k for k in range(lo, b) if W[k]["high"] >= R - CLUSTER_ATR * A]
    body = max(max(W[k]["open"], W[k]["close"]) for k in cluster)
    body = min(body, R)
    width_note = None
    if R - body < MIN_W_ATR * A:
        body, width_note = R - MIN_W_ATR * A, "widened"
    elif R - body > MAX_W_ATR * A:
        body, width_note = R - MAX_W_ATR * A, "clamped"
    return {"top": R, "bottom": body, "pivot": p, "cluster": cluster, "base_lo": lo, "width_note": width_note}


def find(daily: Sequence[Sequence[Any]], asof: Optional[str] = None) -> Dict[str, Any]:
    """The expert zone + significance score of one ticker (see module doc). {'ok': False, 'reason': ...} when none."""
    Wall = weekly(daily)
    if len(Wall) < BASE_W + 10:
        return {"ok": False, "reason": "short history"}
    done = week_complete(Wall[-1]["last"], asof)
    W = Wall if done else Wall[:-1]           # structure from completed weeks only
    n = len(W)
    A = wilder_atr(W)
    if not A:
        return {"ok": False, "reason": "short history"}
    last = Wall[-1]["close"]                  # current price (the running week counts for 'where is price now')
    if n >= 34:
        ma_now = sum(x["close"] for x in W[-30:]) / 30
        ma_4 = sum(x["close"] for x in W[-34:-4]) / 30
        if ma_now < ma_4:
            return {"ok": False, "reason": f"30-week MA falling ({ma_4:.2f} -> {ma_now:.2f}): stage 3/4, not a retest (Weinstein)",
                    "atr_w": round(A, 4)}
    first_reason = None
    for b in range(n - 1, max(BASE_W, n - LOOKBACK_W) - 1, -1):
        R = max(W[k]["high"] for k in range(b - BASE_W, b))
        if not (W[b]["close"] > R >= W[b - 1]["close"]):
            continue
        z = _zone_of(W, b, A)
        if b - z["pivot"] < MIN_BASE_GAP:
            continue
        top, bot = z["top"], z["bottom"]
        post_hi = max(x["high"] for x in Wall[b:])
        reason = None
        if post_hi < top + MOVE_AWAY_ATR * A:
            reason = "never moved away (high after the breakout < top + 1 ATR)"
        elif any(W[k]["close"] < bot * (1 - BREAK_PCT) for k in range(b + 1, n)) or last < bot * (1 - BREAK_PCT):
            reason = "broken (weekly close > 3% under the zone)"
        elif any(W[k]["close"] < bot and W[k + 1]["close"] < bot for k in range(b + 1, n - 1)):
            reason = "broken (two consecutive weekly closes under the zone)"
        elif last > post_hi - PULLBACK_ATR * A:
            reason = "no pullback yet (price within 1 ATR of the post-breakout high)"
        elif last > top + NEAR_ATR * A:
            sh = _shelf(Wall, W, b, z, A, last)   # v4: a higher shelf is the active support -> 'near' is measured to it
            if not (sh and last <= sh["top"] + NEAR_ATR * A):
                reason = f"price {(last - top) / A:.1f} ATR above the base top"
        if reason:
            first_reason = first_reason or f"{reason}; latest breakout {W[b]['time']} over {top:.2f}"
            continue
        res = _result(Wall, W, b, z, A, last, post_hi, daily, _shelf(Wall, W, b, z, A, last))
        res.update(hammers(W, res["top"], res["bottom"], A))
        return res
    return {"ok": False, "reason": first_reason or "no breakout above a 26-week base in 3 years", "atr_w": round(A, 4)}


def _shelf(Wall, W, b, z, A, last) -> Optional[Dict[str, Any]]:
    """Higher shelf above the breakout level (module doc step 4), or None."""
    n, top = len(W), z["top"]
    if not any(W[k]["high"] >= top + MOVE_AWAY_ATR * A for k in range(b, n)):
        return None
    hi = max(range(b, n), key=lambda k: W[k]["high"])   # the post-breakout high: the shelf forms on the pullback after it
    sw = [k for k in range(hi + 1, n - 1) if W[k]["low"] <= W[k - 1]["low"] and W[k]["low"] <= W[k + 1]["low"]
          and W[k]["low"] > top + CLUSTER_ATR * A]
    best = None
    for i in sw:                                   # clusters anchored at each swing low (its lowest member)
        L = W[i]["low"]
        cl = [k for k in sw if L <= W[k]["low"] <= L + CLUSTER_ATR * A]
        if len(cl) < 2:
            continue
        first = min(cl)
        if any(W[k]["close"] < L * (1 - BREAK_PCT) for k in range(first, n)) or last < L * (1 - BREAK_PCT):
            continue
        if any(W[k]["close"] < L and W[k + 1]["close"] < L for k in range(first, n - 1)):
            continue
        key = (min(len(cl), 3), L, max(cl))      # 3+ lows preferred, then the highest, then the most recent
        if best is None or key > best[0]:
            best = (key, i, cl)
    if not best:
        return None
    _, i, cl = best
    L = W[i]["low"]
    body = min(min(W[k]["open"], W[k]["close"]) for k in cl)
    t, note = body, None
    if t - L < MIN_W_ATR * A:
        t, note = L + MIN_W_ATR * A, "widened"
    elif t - L > MAX_W_ATR * A:
        t, note = L + MAX_W_ATR * A, "clamped"
    return {"top": t, "bottom": L, "cluster": sorted(cl), "width_note": note}


HAMMER_WEEKS = 12   # weeks stored; the app filter looks at the last X <= 12 of them


def hammer_shape(o: float, h: float, l: float, c: float) -> Optional[str]:
    """'H' textbook hammer: lower shadow >= 2x body, body in the top third, upper shadow <= 15% of the range;
    'h' near-hammer: lower shadow >= 1.5x body and >= 40% of the range, close in the upper half (Eyal 2026-11-01,
    /workspace/asb_like/scan.py)."""
    R = h - l
    if R <= 0:
        return None
    body, lo, up = abs(c - o), min(o, c) - l, h - max(o, c)
    if lo >= 2 * max(body, 1e-9) and lo >= 2 / 3 * R and up <= 0.15 * R:
        return "H"
    if lo >= 1.5 * max(body, 1e-9) and lo >= 0.4 * R and (c - l) >= 0.5 * R:
        return "h"
    return None


def touches(l: float, c: float, top: float, bot: float, A: float) -> bool:
    """A week touches the zone: low <= top + 0.5 A and (low >= bottom - 0.5 A or close >= bottom)."""
    return l <= top + 0.5 * A and (l >= bot - 0.5 * A or c >= bot)


def hammers(W, top: float, bot: float, A: float, weeks: int = HAMMER_WEEKS) -> Dict[str, Any]:
    """Hammer weeks touching the (active) expert zone and weekly closes under its bottom in the last `weeks` completed
    weeks. k = 1 is the last completed week. The app filter 'פטישים על אזור המומחים' counts them in its own window."""
    n, hw, cb = len(W), [], []
    for k in range(1, min(weeks, n) + 1):
        w = W[n - k]
        s = hammer_shape(w["open"], w["high"], w["low"], w["close"])
        if s and touches(w["low"], w["close"], top, bot, A):
            hw.append({"w": w["time"], "s": s, "k": k})
        if w["close"] < bot:
            cb.append(k)
    return {"hammers": hw, "closes_below_k": cb, "last_week": W[-1]["time"] if W else None}


def _avg(xs: Sequence[float]) -> float:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _sma30_close(Wall: List[Dict[str, Any]]) -> Optional[float]:
    if len(Wall) < 30:
        return None
    return _avg([x["close"] for x in Wall[-30:]])


def _result(Wall, W, b, z, A, last, post_hi, daily, sh=None) -> Dict[str, Any]:
    o_top, o_bot, lo = z["top"], z["bottom"], z["base_lo"]
    top, bot = (sh["top"], sh["bottom"]) if sh else (o_top, o_bot)
    n = len(W)
    base = range(lo, b)
    s0 = sh["cluster"][0] if sh else None
    span = range(s0, n) if sh else base                # weeks that built the zone
    zone_w = [k for k in span if W[k]["low"] <= top and W[k]["high"] >= bot]
    F: List[Dict[str, Any]] = []

    def add(k, pts, mx, val):
        F.append({"k": k, "he": LABEL_HE[k], "pts": pts, "max": mx, "val": val, "src": SRC[k]})

    add("time", min(20.0, 2.5 * len(zone_w)), 20, f"{len(zone_w)} weeks")
    t = len(sh["cluster"]) if sh else _runs(z["cluster"])
    add("touches", 15 if t >= 3 else 10 if t == 2 else 4, 15, f"{t}" + (" (shelf lows)" if sh else ""))
    vb = _avg([W[k]["volume"] for k in (range(b, n) if sh else base)])
    vz = _avg([W[k]["volume"] for k in zone_w])
    vr = vz / vb if vb else 0.0
    add("volume", 10 if vr >= 1.3 else 6 if vr >= 1.0 else 2, 10, f"x{vr:.2f}")
    v10 = _avg([W[k]["volume"] for k in range(max(0, b - 10), b)])
    bv = W[b]["volume"] / v10 if v10 else 0.0
    beyond = (W[b]["close"] - o_top) / o_top
    rng = W[b]["high"] - W[b]["low"]
    upper = rng > 0 and (W[b]["close"] - W[b]["low"]) / rng >= 0.5
    pts = (10 if bv >= 2 else 6 if bv >= 1.5 else 3 if bv >= 1 else 0) + (5 if beyond >= 0.01 else 0) + (5 if upper else 0)
    add("breakout", pts, 20, f"vol x{bv:.2f}, close +{beyond * 100:.1f}%{', upper half' if upper else ''}")
    # retest number: runs of weeks after the breakout whose low came within 0.25 ATR of the top (from above);
    # if price is not at the zone now, the next visit counts as one more
    near = [k for k in range((s0 if sh else b + 1), len(Wall)) if Wall[k]["low"] <= top + 0.25 * A]
    visits = _runs(near)
    at_now = bool(near) and near[-1] == len(Wall) - 1
    no = visits if at_now else visits + 1
    add("retest", 10 if no == 1 else 7 if no == 2 else 3 if no == 3 else 0, 10, f"#{no}")
    age = n - 1 - (sh["cluster"][-1] if sh else b)
    add("recency", 5 if age <= 13 else 3 if age <= 26 else 1 if age <= 52 else 0, 5, f"{age} weeks since " + ("the last shelf low" if sh else "breakout"))
    st = round_step(top)
    rn = [st * k for k in range(int(math.floor((bot - 0.1 * A) / st)), int(math.ceil((top + 0.1 * A) / st)) + 1)
          if bot - 0.1 * A <= st * k <= top + 0.1 * A]
    add("round", 5 if rn else 0, 5, f"{rn[0]:g}" if rn else "-")
    gap = None
    days = [d for k in range(b, min(b + 2, len(Wall))) for d in Wall[k]["days"]]
    first = Wall[b]["days"][0]
    prev_days = [r for r in daily if str(r[0])[:10] < str(first[0])[:10]]
    seq = prev_days[-1:] + days
    for i in range(1, len(seq)):
        ph, l = float(seq[i - 1][2]), float(seq[i][3])
        if l > ph and ph <= o_top + 0.5 * A and l >= o_bot:
            gap = str(seq[i][0])[:10]
            break
    add("gap", 5 if gap else 0, 5, gap or "-")
    conf = 0
    parts = []
    ma = _sma30_close(Wall)
    if ma is not None and bot - 0.5 * A <= ma <= top + 0.5 * A:
        conf += 5
        parts.append(f"MA30 {ma:.2f}")
    sw_lo = min(W[k]["low"] for k in base)
    f38, f62 = post_hi - 0.382 * (post_hi - sw_lo), post_hi - 0.618 * (post_hi - sw_lo)
    if f62 <= top and f38 >= bot:
        conf += 5
        parts.append(f"Fib {f62:.2f}-{f38:.2f}")
    below = [W[k]["last"] for k in range((s0 + 1) if sh else (b + 1), n) if W[k]["close"] < bot]
    add("below", -min(20, 10 * len(below)), 0, ", ".join(below) or "-")
    add("confluence", conf, 10, ", ".join(parts) or (f"MA30 {ma:.2f} (outside)" if ma is not None else "-"))
    score = max(0, int(round(sum(f["pts"] for f in F))))
    trade = _trade(Wall, W, b, top, bot, A, post_hi, sw_lo)
    start = W[s0]["time"] if sh else W[min(z["cluster"])]["time"]
    origin = {"top": round(o_top, 2), "bottom": round(o_bot, 2), "base_start": W[min(z["cluster"])]["time"]}
    shelf = ({"lows": [[W[k]["time"], round(W[k]["low"], 2)] for k in sh["cluster"]], "src": SRC["shelf"]} if sh else None)
    return {
        "ok": True, "top": round(top, 2), "bottom": round(bot, 2), "atr_w": round(A, 4), "origin": origin, "shelf": shelf,
        "base_start": start, "pivot_week": W[z["pivot"]]["time"], "breakout_week": W[b]["time"],
        "breakout_close": round(W[b]["close"], 2), "post_high": round(post_hi, 2), "price": round(last, 2),
        "dist_atr": round((last - top) / A, 2) if last > top else (0.0 if last >= bot else round((last - bot) / A, 2)),
        "width_note": (sh or z)["width_note"], "score": score, "factors": F,
        "trade": trade,
        "warnings": [{"k": "close_below", "date": d, "he": f"סגירה שבועית מתחת לאזור ({d})"} for d in below],
    }


def _trade(Wall, W, b, top, bot, A, post_hi, base_low) -> Dict[str, Any]:
    """Expert entry / SL / TP (see module doc 'EXPERT TRADE')."""
    hi_i = max(range(b, len(Wall)), key=lambda k: Wall[k]["high"])
    retest_low = min(x["low"] for x in Wall[hi_i:])
    entry = top
    sl = min(retest_low, bot) - 0.1 * A
    st = round_step(top)
    rn = math.floor(sl / st) * st + st                      # the round number just above the structural stop
    if rn - sl < 0.1 * A and rn <= bot:                     # a round number right above it -> go under the round number
        sl = rn - 0.1 * A
    notes = []
    if sl > entry - A:
        sl, notes = entry - A, ["widened to 1 weekly ATR"]
    risk_pct = (entry - sl) / entry * 100
    if risk_pct > 8:
        notes.append("risk > 8% (IBD max 7-8%)")
    tp = post_hi
    mm = top + (top - base_low)
    rr = (tp - entry) / (entry - sl) if entry > sl else None
    return {"entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp, 2), "rr": round(rr, 2) if rr is not None else None,
            "tp_mm": round(mm, 2), "retest_low": round(retest_low, 2), "risk_pct": round(risk_pct, 1),
            "confirmed": Wall[-1]["close"] > top, "notes": notes}


def overlap(a_top: float, a_bot: float, b_top: Optional[float], b_bot: Optional[float]) -> Optional[bool]:
    if b_top is None or b_bot is None:
        return None
    return min(a_top, max(b_top, b_bot)) >= max(a_bot, min(b_top, b_bot))


def _yf_rows(t: str) -> Optional[List[List[Any]]]:
    """5y daily rows [date, o, h, l, c, v] from yfinance for a ticker the export has no candles for (kept in memory)."""
    try:
        import yfinance as yf
        df = yf.Ticker(t).history(period="5y", interval="1d", auto_adjust=True)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return [[i.strftime("%Y-%m-%d"), *(round(float(x), 4) for x in r[:4]), float(r[4])] for i, r in zip(df.index, df.values)] or None
    except Exception:
        return None


def build(tickers: Sequence[str], data_dir: Path, asof: Optional[str] = None, fetch: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for t in tickers:
        f = data_dir / "candles" / f"{t}.json"
        rows = json.loads(f.read_text())["d"] if f.exists() else (_yf_rows(t) if fetch else None)
        if not rows:
            out[t] = {"ok": False, "reason": "no candles"}
            continue
        try:
            out[t] = find(rows, asof)
        except Exception as e:  # never block the export
            out[t] = {"ok": False, "reason": f"error: {e}"}
    return out


def _load(data_dir: Path) -> Dict[str, Any]:
    p = data_dir / "expert_zones.json"
    try:
        return json.loads(p.read_text()).get("tickers", {}) if p.exists() else {}
    except Exception:
        return {}


def _save(data_dir: Path, tickers: Dict[str, Any]) -> Path:
    p = data_dir / "expert_zones.json"
    slim = {}
    for t in sorted(tickers):   # factor labels / sources once per file (doc 'labels' / 'sources'), not per ticker
        r = dict(tickers[t])
        if r.get("factors"):
            r["factors"] = [{k: f[k] for k in ("k", "pts", "max", "val")} for f in r["factors"]]
        slim[t] = r
    doc = {"rule_version": RULE_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "labels": LABEL_HE, "sources": SRC, "tickers": slim}
    p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return p


def starred(state_path: Optional[str] = None) -> List[str]:
    """The current starred list as the routine last synced it from Supabase (app_state.json)."""
    from srs_app.sync import APP_STATE, watchlist_from_state
    import os
    return [t for t in watchlist_from_state(state_path or os.environ.get("SRS_APP_STATE", APP_STATE)) if t]


def add(tickers: Sequence[str], data_dir: Path, asof: Optional[str] = None, fetch: bool = True) -> Path:
    """Newly starred: compute these tickers and merge them into the file (others kept as they are)."""
    cur = _load(data_dir)
    cur.update(build(sorted({t.upper() for t in tickers}), data_dir, asof, fetch))
    return _save(data_dir, cur)


def remove(tickers: Sequence[str], data_dir: Path) -> Path:
    cur = _load(data_dir)
    for t in tickers:
        cur.pop(t.upper(), None)
    return _save(data_dir, cur)


def write(tickers: Sequence[str], data_dir: Path, asof: Optional[str] = None, fetch: bool = False) -> Path:
    """Replace the file with exactly these tickers."""
    p = _save(data_dir, build(sorted(set(tickers)), data_dir, asof, fetch))
    return p


def sync_all(data_dir: Path, asof: Optional[str] = None, state_path: Optional[str] = None, fetch: bool = True) -> Path:
    """Nightly (Eyal 2026-11-01 20:47: 'add it to all the stocks'): every ticker the export wrote candles for (all app rows,
    ETFs too) + the starred list (outside the universe: yfinance in memory when no candles). Per-ticker errors become
    'no expert level' with the reason; never raises for one ticker."""
    ts = {f.stem for f in (data_dir / "candles").glob("*.json")}
    try:
        ts |= set(starred(state_path))
    except Exception:
        pass
    return write(sorted(ts), data_dir, asof, fetch)


def sync_starred(data_dir: Path, asof: Optional[str] = None, state_path: Optional[str] = None, fetch: bool = False) -> Optional[Path]:
    """Nightly: the file = the current starred list (unstarred drop out). No list (state missing) -> keep the file's set."""
    ts = starred(state_path)
    return write(ts, data_dir, asof, fetch) if ts else refresh(data_dir, asof)


def refresh(data_dir: Path, asof: Optional[str] = None) -> Optional[Path]:
    """Nightly: recompute the tickers already in expert_zones.json (the starred set it was built for)."""
    p = data_dir / "expert_zones.json"
    if not p.exists():
        return None
    return write(list(json.loads(p.read_text()).get("tickers", {})), data_dir, asof)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--starred", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--add", default="")
    ap.add_argument("--remove", default="")
    ap.add_argument("--data", default=str(Path(__file__).resolve().parent.parent / "app" / "data"))
    ap.add_argument("--asof", default=None)
    a = ap.parse_args(argv)
    d = Path(a.data)
    lst = lambda x: [t.strip().upper() for t in x.split(",") if t.strip()]
    if a.add:
        p = add(lst(a.add), d, a.asof)
    elif a.remove:
        p = remove(lst(a.remove), d)
    elif a.all:
        p = sync_all(d, a.asof)
    elif a.starred:
        p = sync_starred(d, a.asof, fetch=True)
    elif a.refresh:
        p = refresh(d, a.asof)
    else:
        p = write(lst(a.tickers), d, a.asof)
    if p:
        for t, r in json.loads(p.read_text())["tickers"].items():
            print(t, (f"{r['bottom']}-{r['top']} score {r['score']} breakout {r['breakout_week']}" if r["ok"] else "no expert level: " + r["reason"]))


if __name__ == "__main__":
    main()
