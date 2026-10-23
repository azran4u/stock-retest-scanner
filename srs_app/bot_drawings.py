"""Bot drawings for app candidates that need one (policy 2026-10-23: bot drawings are approved by default).

Rules = v3d (fitted on Eyal's 54 TradingView drawings; research in /workspace/drawing-learn, rule code vendored in
srs_app/v3d/ so production and the golden test never depend on the box; params frozen below):
  zone  = clearest valid weekly level below price: RETEST of a broken pivot high (body top -> wick high) or
          BACK-TO-SUPPORT pivot low (wick low -> body bottom), clarity >= 3, body pivot, wick edge capped at 0.5 ATR;
          a level is broken (skipped) if ANY price traded below its SL since the pivot (grace 3 weeks for closes);
          among valid levels pick the one nearest the pullback low / price / 38.2% retracement;
  entry = zone top - 0.13 ATR;  SL = entry - 1 weekly Wilder ATR, unless the lowest pullback / near-zone wick low
          (last 52 weeks, within 0.75 ATR below the zone) gives risk 0.9-1.2 ATR -> just under that wick;
  TP    = highest weekly body top of the last 26 weeks - 0.09 ATR.
Long Position is time-anchored: t_start = the week right after the last candle, t_end = +20 weekly bars.
Each row carries meta = {rule_version, why{...}} so feedback can be analyzed later.

Candidates: f_dollar_vol AND f_history AND f_no_earnings_14d AND f_technical, no live user/tv drawing, no active
'not interesting' mark, not one of his lines-only charts (tv_source user-lines), no 'structure' feedback in the last 8 weeks, and no live bot drawing (unless it is broken:
any price since it was drawn below its SL, latest close >= TP, or close > zone top + 3 ATR -> obsolete + redraw).
A zone more than FAR_CAP_ATR (3) weekly ATRs below the close is never drawn (it would be 'far' on arrival). A bot drawing rejected via feedback under the current
RULE_VERSION is not redrawn until the rule version changes.

    # 1) read state through the Supabase connector (execute_sql), save the JSON outputs:
    python -m srs_app.bot_drawings --print-read-sql
    # 2) compute + emit SQL (run the printed statements with execute_sql):
    python -m srs_app.bot_drawings --drawings-json D.json --labels-json L.json --feedback-json F.json --emit-sql
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

RULE_VERSION = "v4-2026-10-23"  # v4: touch-count zone scoring with recency (his principle) on top of v3e; v3e: reclaimed levels count again + pullback from the latest swing high (QCOM) + last higher low with clarity 2 (TWST) + reclaimed level not above price; c: one-day spike wicks ignored when picking the level (HWC); b: b: FAR_CAP_ATR (no zone > 3 ATR below the close) + retire target-hit / far
LEARN_DIR = Path(os.environ.get("SRS_DRAWING_LEARN", str(Path(__file__).resolve().parent / "v3d")))  # vendored v3d rule code
REPORT = Path(__file__).resolve().parent.parent / "historical-reports" / "latest.csv"
LONG_W_BARS = 20
STRUCTURE_EXCLUDE_WEEKS = 8
# A zone more than this many weekly ATRs below the latest close is not drawn: the obsolete check (report_filters
# stale_far_atr = 3) would flag it 'far' on arrival, and none of his 37 zone drawings was more than 1.8 ATR below
# price when drawn (drawing-learn/features.csv close_vs_zt_atr max 1.77). BMO / RY 2026-10-23: 3.25 / 3.63 ATR.
FAR_CAP_ATR = 3.0
# v3e (QCOM zone feedback, approved by him 2026-10-23; accepted that COP / MA / OXY / WTRG move away from his drawings):
#  RECLAIM      - a level that broke (a close or low under its SL) and was then reclaimed by >= RECLAIM_CLOSES weekly
#                 closes back above its top counts again; only the bars since the reclaim are checked for breaks.
#  SWING_ANCHOR - the current pullback is measured from the latest swing high (a high >= 2 ATR above the 26-week
#                 pullback low, followed by >= 1 ATR of decline), not from the 26-week high.
RECLAIM = True
RECLAIM_CLOSES = 2
SWING_ANCHOR = True
SWING_MIN_ATR = 2.0
# Zone must sit at/below the current price (TWST 2026-10-23: the reclaimed 145.59-155.44 level was picked with price
# 135.47 under it). "reclaimed" (shipped): a reclaimed level the price has fallen back under is not a support - its
# bottom must be <= close + ABOVE_PRICE_TOL_ATR (QCOM's reclaimed 176.95 is 0.26 ATR above the 172.83 close, like his
# own 173.47 zone; TWST's 145.59 is 0.37 ATR above). "all" = same test for every level: on his 99 own zones mean IoU
# 0.325 vs 0.334 ("reclaimed"), because v3d retests-in-progress slightly under price match him (BWA, FSM, FWONK, WDC).
ABOVE_PRICE_GUARD = "reclaimed"
ABOVE_PRICE_TOL_ATR = 0.3
# LAST_HL (TWST feedback, policy 2026-10-23: his old drawings are a soft reference, the bot decides the zone):
# in a run-up the base after the breakout candle = the last higher low (support pivot) before the latest 26-week
# high counts even with clarity 2 (< s_min 3), when its body clarity is >= 2 and it is not broken.
LAST_HL = True
LAST_HL_MIN_CLARITY = 2
# TOUCH SCORING (his principle 2026-10-23: the PRIMARY zone criterion is the touch count = how many weekly (and daily)
# closes or wicks reached the zone; pivot clarity is only a sanity check / tie-breaker). A bar touches when its close,
# low or high lies inside [zone bottom - TOUCH_TOL_ATR x ATR, zone top + TOUCH_TOL_ATR x ATR]; consecutive touching
# bars count as one touch; counted over the last TOUCH_LOOKBACK_W weeks. Pick = max of weekly touches
#   - PROX_W x (ATR from the close down to the zone top) - RECENCY_W x (age of the underlying pivot in years);
# ties -> daily touches -> newer pivot -> clarity. Weights from a sweep (lookback 52/104/156, PROX 1.5/3, RECENCY 1/3/6):
# the only set that keeps TWST / QCOM / HWC on his current zones with the best soft match on his old drawings.
ZONE_SCORING = "touches"   # "touches" | "v3d"
TOUCH_TOL_ATR = 0.25
TOUCH_LOOKBACK_W = 52
TOUCH_MIN_CLARITY = 2      # sanity: a swing pivot with >= 2 weekly bars on each side
PROX_W = 3.0
RECENCY_W = 6.0  # per year of pivot age: the RECENT support / resistance wins among viable levels (his rule)  # zone bottom may sit at most this many weekly ATR above the close (retest in progress)
# v3d parameters (fit on all 54 of his drawings, bot_drawings.json 'fit'; frozen so runs are reproducible)
FIT = dict(grace=3, wick_n=1, body_piv=2, s_min=3, wick_cap=0.5, L=52, X=0.75, lo=0.9, hi=1.2, mode="fit")

SQL_READ = {
    "drawings": "select id, ticker, kind, zone_top, zone_bottom, entry, stop, target, t_start, t_end, source, status, "
                "meta, created_at, updated_at from public.drawings where status in ('active','approved','review','rejected') "
                "order by ticker, kind;",
    "labels": "select distinct on (ticker, label) ticker, label, value, asof, until from public.labels "
              "where label = 'not_interesting' order by ticker, label, asof desc, created_at desc;",
    "feedback": "select ticker, category, created_at, rule_version from public.drawing_feedback order by created_at;",
}

_R: Dict[str, Any] = {}
_DEBUG: Dict[str, Any] = {}


def _rules():
    """Lazy import of the v3d research modules (they load hist_cache.pkl on import)."""
    if not _R:
        for p in (str(LEARN_DIR),):
            if p not in sys.path:
                sys.path.insert(0, p)
        import infer as V1  # noqa
        import infer_v3 as V3  # noqa
        import infer_v3d as V3D  # noqa
        _R.update(V1=V1, V3=V3, V3D=V3D,
                  P={**V3.DEFAULT, **V3D.FIXED, **FIT, "long_wick": 99, "close_n": 99})
    return _R


def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "yes", "1")


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# An isolated one-day wick (low more than SPIKE_K x the 20-day median true range below BOTH neighbouring days' lows,
# with open and close in the top quarter of the bar) is treated as a bad print / flash wick when choosing the level:
# HWC 2026-10-14 low 65.47 (neighbours 71.81 / 72.00, close 71.87, normal volume) made v3d call the Feb-2026 high /
# Jun-Oct support 72.5-73.8 "broken" and draw 62.4-63.3 instead; he drew 72.53-73.6 with SL 69.69 above that wick.
# Only level selection uses the cleaned lows; the obsolete check (low_since) still counts every wick, as he asked.
SPIKE_K = 3.0


def despike_lows(d, k: float = SPIKE_K):
    """Copy of daily OHLC with isolated one-day spike lows clipped to min(open, close); returns (df, spike dates)."""
    import numpy as np
    l, h, o, c = (d[x].to_numpy(dtype=float) for x in ("Low", "High", "Open", "Close"))
    if len(l) < 3:
        return d, []
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.c_[h - l, np.abs(h - pc), np.abs(l - pc)], axis=1)
    import pandas as pd
    m = pd.Series(tr).rolling(20, min_periods=10).median().shift(1).to_numpy()
    nb = np.minimum(np.r_[np.inf, l[:-1]], np.r_[l[1:], np.inf])
    rng = np.where(h - l > 0, h - l, np.nan)
    with np.errstate(invalid="ignore"):
        s = (l < nb - k * m) & ((c - l) / rng >= 0.75) & ((o - l) / rng >= 0.75)
    s[0] = s[-1] = False
    if not s.any():
        return d, []
    d = d.copy()
    col = d.columns.get_loc("Low")
    for i in np.where(s)[0]:
        d.iat[i, col] = min(o[i], c[i])
    return d, [str(x.date()) for x in d.index[s]]


def _clear_caches() -> None:
    """The v3d helpers memoize on (ticker, date); drop them when the price frame behind a ticker is swapped."""
    import sys as _s
    for mod, fn in (("infer", "ctx"), ("infer_v2", "raw_levels"), ("infer_v3", "raw_v3"), ("infer_v3d", "sl_d")):
        f = getattr(_s.modules.get(mod), fn, None)
        if f is not None and hasattr(f, "cache_clear"):
            f.cache_clear()


def valid_levels(t: str, rd: str, reclaim: bool = RECLAIM, last_hl: Optional[bool] = None) -> List[Dict[str, Any]]:
    """v3d valid levels (infer_v3d.valid_levels_d + "no low under the SL since the pivot"), plus v3e RECLAIM:
    after the last break (a weekly close or low under the SL) a level whose top was closed above on
    >= RECLAIM_CLOSES later weeks is re-validated, and only the weeks from the first reclaim close on are checked."""
    R = _rules()
    V1, V3, V3D, P = R["V1"], R["V3"], R["V3D"], R["P"]
    last_hl = LAST_HL if last_hl is None else last_hl
    s_min = TOUCH_MIN_CLARITY if ZONE_SCORING == "touches" else P["s_min"]
    Pz = dict(P, s_min=s_min)
    if ZONE_SCORING == "touches":
        last_hl = False  # covered: clarity 2 levels are candidates anyway
    C = V1.ctx(t, rd)
    A = C["atr"]
    g = int(P["grace"])
    ref_close = C["c"][-1 - g]
    res = []
    for z in V3.raw_v3(t, rd, P["wick_cap"]):
        if z["strength"] < s_min or z["zb"] > ref_close or not V3D.zone_ok(z, C, Pz):
            continue
        e = z["zt"] - V3.ENTRY_BELOW_TOP * A
        sl, src = V3D.sl_d(t, rd, z["zb"], z["zt"], e, *V3D.slp(P))
        slr, ztr = (sl - z["zb"]) / A, (z["zt"] - z["zb"]) / A
        cr, lr = list(z["closes_rel"]), list(z["lows_rel"])
        k0 = 0
        if reclaim:
            brk = [j for j in range(len(cr)) if cr[j] < slr or lr[j] < slr]
            if brk:
                above = [j for j in range(brk[-1] + 1, len(cr)) if cr[j] > ztr]
                if len(above) >= RECLAIM_CLOSES:
                    k0 = above[0]
        cr2, lr2 = cr[k0:], lr[k0:]
        crg = cr2[:len(cr2) - g] if g else cr2
        lrg = lr2[:len(lr2) - g] if g else lr2
        if len(crg) and min(crg) < slr:
            continue
        if sum(1 for x in lrg if x < slr) >= P["wick_n"]:
            continue
        if lr2 and min(lr2) < slr:  # bot rule: no low under the SL at all (since the pivot / the reclaim)
            continue
        zz = dict(z, sl=sl, sl_src=src, reclaimed=k0 > 0)
        if k0:
            zz["reclaim_i"] = C["n"] - len(cr) + k0  # closes_rel runs over the weeks after the pivot up to the last week
        res.append(zz)
    if last_hl:
        res += last_hl_level(t, rd, res)
    return res


def last_hl_level(t: str, rd: str, have: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LAST_HL: the most recent support pivot before the 26-week high, if it is not already a valid level and only
    misses the clarity bar (>= LAST_HL_MIN_CLARITY), sits below the price (as of the grace bar) and was never broken."""
    R = _rules()
    V1, V3, V3D, P = R["V1"], R["V3"], R["V3D"], R["P"]
    C = V1.ctx(t, rd)
    A, g = C["atr"], int(P["grace"])
    sup = [z for z in V3.raw_v3(t, rd, P["wick_cap"]) if z["kind"] == "support" and z["i"] < C["ihi"]]
    if not sup:
        return []
    z = max(sup, key=lambda z: z["i"])
    if any(h["kind"] == z["kind"] and h["i"] == z["i"] for h in have):
        return []
    if z["strength"] < LAST_HL_MIN_CLARITY or min(V3.strength(C["bb"], z["i"], "lo")) < LAST_HL_MIN_CLARITY:
        return []
    if z["zb"] > C["c"][-1 - g]:
        return []
    e = z["zt"] - V3.ENTRY_BELOW_TOP * A
    sl, src = V3D.sl_d(t, rd, z["zb"], z["zt"], e, *V3D.slp(P))
    slr = (sl - z["zb"]) / A
    cr, lr = list(z["closes_rel"]), list(z["lows_rel"])
    if (cr and min(cr) < slr) or (lr and min(lr) < slr):
        return []
    return [dict(z, sl=sl, sl_src=src, reclaimed=False, last_hl=True)]


def touches(lo: Any, hi: Any, cl: Any, zb: float, zt: float, tol: float) -> tuple:
    """(# touches, index of the last touching bar or -1): bars whose close, low or high lies in [zb - tol, zt + tol];
    a run of consecutive touching bars is one touch."""
    import numpy as np
    a, b = zb - tol, zt + tol
    inb = lambda x: (x >= a) & (x <= b)
    m = inb(np.asarray(cl)) | inb(np.asarray(lo)) | inb(np.asarray(hi))
    if not m.any():
        return 0, -1
    starts = m & ~np.r_[False, m[:-1]]
    return int(starts.sum()), int(np.where(m)[0][-1])


def _below_price_ok(z: Dict[str, Any], last: float, A: float) -> bool:
    if ABOVE_PRICE_GUARD == "all" or (ABOVE_PRICE_GUARD == "reclaimed" and z.get("reclaimed")):
        return z["zb"] <= last + ABOVE_PRICE_TOL_ATR * A
    return True


def pullback_anchor(C: Dict[str, Any], swing: bool = SWING_ANCHOR):
    """(pullback low, recent high, fib anchor low, swing used?). v3d: low since the 26-week high. v3e SWING_ANCHOR: when
    a new swing high (>= SWING_MIN_ATR above that low, then >= 1 ATR of decline) formed after it, the current pullback
    is measured from that swing high and the fib runs from the earlier low to it."""
    R = _rules()
    V1 = R["V1"]
    import numpy as np
    A, l, h, n = C["atr"], C["l"], C["h"], C["n"]
    pb, rh, lo = float(C["pb_low"]), float(C["rh"]), V1.fib_anchor_low(C, 52)
    if swing and C["ihi"] < n - 2:
        ipb = C["ihi"] + 1 + int(np.argmin(l[C["ihi"] + 1:]))
        if ipb < n - 2:
            i2 = ipb + 1 + int(np.argmax(h[ipb + 1:]))
            if h[i2] - pb >= SWING_MIN_ATR * A and i2 < n - 1 and h[i2] - l[i2 + 1:].min() >= 1.0 * A:
                return float(l[i2 + 1:].min()), float(h[i2]), pb, True
    return pb, rh, lo, False


def compute(ticker: str, read_date: Optional[str] = None) -> Dict[str, Any]:
    """Zone + Long Position for one ticker (v3d) on spike-cleaned lows. has_level False -> reason, no levels."""
    R = _rules()
    V1 = R["V1"]
    t = ticker.upper()
    raw = V1.H.get(t)
    if raw is None or raw.empty:
        return _compute(t, read_date)
    clean, sp = despike_lows(raw)
    if not sp:
        return _compute(t, read_date)
    V1.H[t] = clean
    _clear_caches()
    try:
        r = _compute(t, read_date)
    finally:
        V1.H[t] = raw
        _clear_caches()
    if r.get("why") is not None:
        r["why"]["ignored_spike_lows"] = sp[-5:]
    return r


def _compute(ticker: str, read_date: Optional[str] = None) -> Dict[str, Any]:
    import pandas as pd
    R = _rules()
    V1, V3, V3D, P = R["V1"], R["V3"], R["V3D"], R["P"]
    import numpy as np
    t = ticker.upper()
    if t not in V1.H or V1.H[t] is None or V1.H[t].empty:
        return dict(ticker=t, has_level=False, reason="no price history in the scanner cache")
    rd = read_date or str(V1.H[t].index.max().date())
    C = V1.ctx(t, rd)
    A, Aw, last = C["atr"], C["atr_w"], C["c"][-1]
    out: Dict[str, Any] = dict(ticker=t, data_date=rd, price=round(float(last), 2), rule_version=RULE_VERSION)
    dly = V1.H[t]["Close"].tail(130)
    jump = float((dly / dly.shift() - 1).abs().max())
    if jump > 0.4:
        return dict(out, has_level=False, reason=f"data issue: {jump:.0%} one-day jump in 26 weeks (split?)")
    zones = valid_levels(t, rd, reclaim=RECLAIM)
    zones = [z for z in zones if _below_price_ok(z, last, A)]
    if not zones:
        return dict(out, has_level=False, reason="no valid level: every clear retest/support below price is broken or none exists")
    near = [z for z in zones if (last - z["zt"]) / A <= FAR_CAP_ATR]
    if not near:
        d = min((last - z["zt"]) / A for z in zones)
        return dict(out, has_level=False, reason=f"price ran away: nearest valid level is {d:.2f} ATR below the close "
                                                 f"(> {FAR_CAP_ATR:g} ATR = obsolete 'far'); no drawing until a closer level forms")
    zones = near
    # (v3d keeps zones the price dipped under within the grace weeks: a retest in progress, as in his drawings)
    pb, rh, lo52, swing = pullback_anchor(C, swing=SWING_ANCHOR)
    fib382 = rh - 0.382 * (rh - lo52)
    # touch counts (weekly = primary, daily = tie-breaker), stored on every candidate
    w_ = C["w"].iloc[-TOUCH_LOOKBACK_W:]
    d_ = V1.H[t]
    d_ = d_[(d_.index >= w_.index[0] - timedelta(days=7)) & (d_.index <= pd.Timestamp(rd))]
    tol = TOUCH_TOL_ATR * A
    nw = len(w_)
    for z in zones:
        z["touches_w"], lw = touches(w_["Low"].values, w_["High"].values, w_["Close"].values, z["zb"], z["zt"], tol)
        z["touches_d"], _ = touches(d_["Low"].values, d_["High"].values, d_["Close"].values, z["zb"], z["zt"], tol)
        z["weeks_since_touch"] = (nw - 1 - lw) if lw >= 0 else nw
        z["pivot_age_w"] = int(C["n"] - 1 - z["i"])
        z["dist_atr"] = round(max(0.0, (last - z["zt"]) / A), 2)
    _DEBUG["zones"] = zones
    if ZONE_SCORING == "touches":
        def tscore(z):
            return (z["touches_w"] - PROX_W * max(0.0, (last - z["zt"]) / A) - RECENCY_W * z["pivot_age_w"] / 52.0,
                    z["touches_d"], -z["pivot_age_w"], z["strength"])
        ch = max(zones, key=tscore)
    else:
        ch = min(zones, key=lambda z: 0.5 * V1.zdist(pb, z["zb"] - 0.3 * A, z["zt"] + 0.3 * A) / A
                 + 0.6 * V1.zdist(last, z["zb"], z["zt"]) / A + 0.3 * abs((z["zb"] + z["zt"]) / 2 - fib382) / A)
    zb, zt = float(ch["zb"]), float(ch["zt"])
    en = zt - V3.ENTRY_BELOW_TOP * A
    sl = float(ch["sl"])
    tp = float(C["bt26"] + V3.TP_OFF * A)
    w, i = C["w"], ch["i"]
    piv = str(w.index[i].date())
    bo = ""
    if ch["kind"] == "retest":
        b = np.where(C["c"][i + 1:] > zt)[0]
        bo = str(w.index[i + 1 + int(b[0])].date()) if len(b) else ""
    last_week = _monday(datetime.strptime(rd, "%Y-%m-%d").date())
    t_start = last_week + timedelta(days=7)
    why = {
        "rule": "v4", "branch": ch["kind"], "pivot_date": piv, "breakout_date": bo or None,
        "clarity": int(ch["strength"]), "wick_confirmations": int(ch.get("conf", 0)),
        "sl_src": ch["sl_src"], "sl_wick_low": round(sl, 2) if ch["sl_src"] == "wick_low" else None,
        "atr": round(A, 4), "atr_w": round(Aw, 4), "risk_atr_w": round((en - sl) / Aw, 2),
        "pullback_low": round(pb, 2), "recent_high": round(rh, 2), "fib382": round(fib382, 2),
        "swing_anchor": swing, "reclaimed": bool(ch.get("reclaimed")), "last_hl": bool(ch.get("last_hl")),
        "zone_scoring": ZONE_SCORING, "touches_w": int(ch["touches_w"]), "touches_d": int(ch["touches_d"]),
        "weeks_since_touch": int(ch["weeks_since_touch"]), "touch_tol_atr": TOUCH_TOL_ATR,
        "pivot_age_w": int(ch["pivot_age_w"]), "touch_lookback_w": TOUCH_LOOKBACK_W,
        "alt_levels": [{"zb": round(float(z["zb"]), 2), "zt": round(float(z["zt"]), 2), "touches_w": int(z["touches_w"]),
                        "touches_d": int(z["touches_d"]), "pivot_age_w": int(z["pivot_age_w"])} for z in sorted(zones, key=lambda z: -z["touches_w"])[:4]],
        "reclaim_date": str(w.index[ch["reclaim_i"]].date()) if ch.get("reclaimed") else None,
        "n_valid_levels": len(zones), "price_below_zone": bool(last < zb), "dist_price_to_zone_top_atr": round((last - zt) / A, 2),
        "entry_rule": "zone_top - 0.13 ATR", "tp_rule": "max 26w body top - 0.09 ATR", "data_date": rd,
    }
    return dict(out, has_level=True, zone_top=round(zt, 2), zone_bottom=round(zb, 2), entry=round(en, 2),
                stop=round(sl, 2), target=round(tp, 2), rr=round((tp - en) / (en - sl), 2) if en > sl else None,
                zone_t_start=piv, t_start=t_start.isoformat(),
                t_end=(t_start + timedelta(days=7 * LONG_W_BARS)).isoformat(), why=why)


# ---------------- candidate selection ----------------
def _meta(r: Dict[str, Any]) -> Dict[str, Any]:
    m = r.get("meta")
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            m = None
    return m if isinstance(m, dict) else {}


def ni_active(labels: Iterable[Dict[str, Any]], today: str) -> set:
    return {str(l["ticker"]).upper() for l in labels if l.get("label", "not_interesting") == "not_interesting"
            and str(l.get("value")).lower() == "yes" and (not l.get("until") or str(l["until"])[:10] >= today)}


def low_since(ticker: str, since: str) -> Optional[float]:
    V1 = _rules()["V1"]
    d = V1.H.get(ticker)
    if d is None or d.empty:
        return None
    d = d[d.index >= since]
    return float(d["Low"].min()) if len(d) else None


def close_atr(ticker: str) -> Optional[tuple]:
    """(latest close, weekly ATR(14)) from the scanner cache, same basis as report_filters.compute_stale."""
    V1 = _rules()["V1"]
    d = V1.H.get(ticker)
    if d is None or d.empty:
        return None
    import report_filters as rf
    import stock_screen as ss
    try:
        a = ss.atr_series(ss.to_weekly(d), int(rf.CONFIG["near_zone_atr_period"])).dropna()
        atr = float(a.iloc[-1]) if len(a) else None
    except Exception:
        atr = None
    return float(d["Close"].iloc[-1]), atr


def bot_obsolete(ticker: str, bots: List[Dict[str, Any]], today: str, low_fn=low_since, price_fn=close_atr) -> List[str]:
    """Why a live bot drawing is obsolete (same rules as report_filters.compute_stale), [] if still valid:
    broken = any low since it was drawn < SL; target hit = latest close >= TP;
    far = latest close > zone top + FAR_CAP_ATR x weekly ATR."""
    f = lambda v: None if v is None else float(v)
    longs = [d for d in bots if d.get("kind") == "long"]
    zones = [d for d in bots if d.get("kind") == "zone"]
    stops = [f(d.get("stop")) for d in longs if d.get("stop") is not None]
    tps = [f(d.get("target")) for d in longs if d.get("target") is not None]
    tops = [f(d.get("zone_top")) for d in zones if d.get("zone_top") is not None]
    out = []
    since = min(str(d.get("created_at") or today)[:10] for d in bots)
    lo = low_fn(ticker, since) if stops else None
    if stops and lo is not None and lo < min(stops):
        out.append("broken")
    if tps or tops:
        pa = price_fn(ticker)
        if pa:
            px, atr = pa
            if tps and px >= min(tps):
                out.append("target hit")
            if tops and atr and px > max(tops) + FAR_CAP_ATR * atr:
                out.append("far")
    return out


def plan(report_rows: Iterable[Dict[str, Any]], drawings: Iterable[Dict[str, Any]], labels: Iterable[Dict[str, Any]],
         feedback: Iterable[Dict[str, Any]], today: Optional[str] = None, low_fn=low_since,
         price_fn=close_atr) -> Dict[str, Any]:
    """Which tickers to draw / redraw. Returns {draw: [t], obsolete: {t: [ids]}, why_obsolete: {t: [flags]}, skip: {t: reason}}.
    A live bot drawing that is broken / target hit / far is marked obsolete; it is redrawn only when the ticker is
    still a candidate (live bot rows of tickers outside the candidate list are only retired)."""
    today = today or date.today().isoformat()
    ni = ni_active(labels, today)
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(weeks=STRUCTURE_EXCLUDE_WEEKS)).isoformat()
    structure = {str(f["ticker"]).upper() for f in feedback
                 if f.get("category") == "structure" and str(f.get("created_at") or "") >= cutoff}
    by_t: Dict[str, List[Dict[str, Any]]] = {}
    for d in drawings:
        by_t.setdefault(str(d["ticker"]).upper(), []).append(d)
    draw, obsolete, why, skip = [], {}, {}, {}
    seen = set()
    for r in report_rows:
        t = str(r["ticker"]).upper()
        if not all(_truthy(r.get(c)) for c in ("f_dollar_vol", "f_history", "f_no_earnings_14d", "f_technical")):
            continue
        if str(r.get("tv_source") or "") == "user-lines":
            skip[t] = "his own Fib / horizontal lines (user-lines)"; continue
        rows = by_t.get(t, [])
        live = [d for d in rows if d.get("status") in ("active", "approved", "review")]
        if any(d.get("source") in ("user", "tv") for d in live):
            continue  # his drawing (or an imported TV one) - never touched
        if t in ni:
            skip[t] = "not interesting"; continue
        if t in structure:
            skip[t] = f"structure feedback < {STRUCTURE_EXCLUDE_WEEKS}w"; continue
        bots = [d for d in live if d.get("source") == "bot"]
        if bots:
            seen.add(t)
            fl = bot_obsolete(t, bots, today, low_fn, price_fn)
            if fl:
                obsolete[t] = [d["id"] for d in bots]
                why[t] = fl
                draw.append(t)
            else:
                skip[t] = "live bot drawing"
            continue
        rej = [d for d in rows if d.get("source") == "bot" and d.get("status") == "rejected"]
        if any(_meta(d).get("rule_version") == RULE_VERSION for d in rej):
            skip[t] = "rejected under the current rule version"; continue
        draw.append(t)
    # live bot drawings of tickers not handled above (dropped out of the screen, or next to his own drawing): retire only
    for t, rows in by_t.items():
        if t in seen:
            continue
        bots = [d for d in rows if d.get("source") == "bot" and d.get("status") in ("active", "approved", "review")]
        if not bots:
            continue
        fl = bot_obsolete(t, bots, today, low_fn, price_fn)
        if fl:
            obsolete[t] = [d["id"] for d in bots]
            why[t] = fl
    return {"draw": draw, "obsolete": obsolete, "why_obsolete": why, "skip": skip}


def emit_sql(results: List[Dict[str, Any]], obsolete: Dict[str, List[str]]) -> List[str]:
    from srs_app.sync import sql_insert_bot_drawing, sql_mark_obsolete
    out = []
    for ids in obsolete.values():
        out += [sql_mark_obsolete(i) for i in ids]
    for r in results:
        if not r.get("has_level"):
            continue
        meta = {"rule_version": RULE_VERSION, "why": r["why"]}
        note = f"BOT {RULE_VERSION}: {r['why']['branch']} {r['why']['pivot_date']}, SL {r['why']['sl_src']}"
        out.append(sql_insert_bot_drawing(r["ticker"], "zone", zone_top=r["zone_top"], zone_bottom=r["zone_bottom"],
                                          t_start=r["zone_t_start"], note=note, meta=meta))
        out.append(sql_insert_bot_drawing(r["ticker"], "long", entry=r["entry"], stop=r["stop"], target=r["target"],
                                          t_start=r["t_start"], t_end=r["t_end"], note=note, meta=meta))
    return out


def _load_rows(p: Optional[str]) -> List[Dict[str, Any]]:
    if not p:
        return []
    from srs_app.app_drawings import load_rows  # tolerant of raw connector output
    return load_rows(Path(p))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--print-read-sql", action="store_true")
    ap.add_argument("--report", default=str(REPORT))
    ap.add_argument("--drawings-json"); ap.add_argument("--labels-json"); ap.add_argument("--feedback-json")
    ap.add_argument("--tickers", help="comma list: compute only these (ignores selection)")
    ap.add_argument("--emit-sql", action="store_true")
    ap.add_argument("--out", help="also write the plan + results JSON here")
    a = ap.parse_args()
    if a.print_read_sql:
        for k, v in SQL_READ.items():
            print(f"-- {k}\n{v}")
        return
    import pandas as pd
    if a.tickers:
        pl = {"draw": [t.strip().upper() for t in a.tickers.split(",") if t.strip()], "obsolete": {}, "skip": {}}
    else:
        rows = pd.read_csv(a.report).to_dict("records")
        pl = plan(rows, _load_rows(a.drawings_json), _load_rows(a.labels_json), _load_rows(a.feedback_json))
    res = [compute(t) for t in pl["draw"]]
    if a.out:
        Path(a.out).write_text(json.dumps({"plan": pl, "results": res}, indent=1, default=str))
    if a.emit_sql:
        print("\n".join(emit_sql(res, pl["obsolete"])))
    else:
        for r in res:
            print(r["ticker"], "LEVEL" if r.get("has_level") else "none", {k: r.get(k) for k in
                  ("zone_bottom", "zone_top", "entry", "stop", "target", "rr")} if r.get("has_level") else r.get("reason"))
        print("skip:", pl["skip"])
        print("obsolete:", pl.get("why_obsolete"))


if __name__ == "__main__":
    main()
