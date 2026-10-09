#!/usr/bin/env python3
"""Standalone report filters — every rule computed for EVERY FinViz row.

Each filter is an independent boolean column (`f_*`) plus its value column(s).
Nothing short-circuits: a ticker that fails $vol still gets short float,
earnings, retest geometry, R:R, streak and reversal values. Missing data ->
False with a note in `filter_notes`.

`status` = PASS iff ALL core filters are true (drives the Grok watchlist
sync): f_dollar_vol, f_short_float, f_no_earnings_14d, f_history, f_rr.
The smooth/reversal filters never change PASS.

f_rr = the user's TradingView drawing (latest stored reading in
stock-screener/tv_drawings.json) found AND its TradingView R:R >= RR_MIN.
A missing / not-found drawing is an R:R failure. tv_* columns carry the
reading (zone top/bottom, entry, SL, TP, R:R, read date).
The scanner's own retest geometry (zone_lo/zone_hi/entry/sl/tp/rr) is still
computed as internal, never-displayed info; its old flag is f_rr_computed
(setup computed AND computed R:R >= RR_MIN) and is NOT part of status.

All thresholds / lookbacks live in CONFIG below (core screen numbers come from
stock_screen.py so there is one definition). Override per run on the CLI,
e.g. `--min-smooth-streak-weeks 6 --daily-reversal-lookback-days 5`.

Backfill / recompute an existing report from cache only (no network):
  python report_filters.py --report historical-reports/latest.csv \
      --report historical-reports/2026-09-28.csv --date 2026-09-28
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# fallbacks when run from the bot copy (/workspace/stock-screener has no stock_screen.py)
for _d in (Path("/workspace/publish-stock-retest-scanner"), Path("/workspace")):
    if (_d / "stock_screen.py").exists() and str(_d) not in sys.path:
        sys.path.append(str(_d))
import stock_screen as ss  # noqa: E402  (publish copy; screen constants live here)

for _d in (_HERE, Path("/workspace")):
    if (_d / "smooth_support_analysis.py").exists() and str(_d) not in sys.path:
        sys.path.append(str(_d))
import smooth_support_analysis as ssa  # noqa: E402  (weekly shapes / streak / smooth_pullback)

# ---------------------------------------------------------------------------
# CONFIG — single place for every filter threshold / lookback (CLI overridable)
# ---------------------------------------------------------------------------
CONFIG: Dict[str, Any] = {
    # core screen rules (values defined once in stock_screen.py)
    "dollar_vol_min": float(ss.DOLLAR_VOL_MIN),          # f_dollar_vol: 30d avg $vol >= $50M
    "avg_vol_days": int(ss.AVG_VOL_DAYS),                # 30d avg volume x last close
    "short_float_max_pct": float(ss.SHORT_FLOAT_MAX) * 100.0,  # f_short_float: < 5%
    "earnings_blackout_days": int(ss.EARNINGS_BLACKOUT_DAYS),  # f_no_earnings_14d
    "min_weekly_bars": int(ss.MIN_WEEKLY_BARS),          # f_history: >= 150 weekly bars (~3y)
    "rr_min": float(ss.RR_MIN),                          # f_rr: retest setup AND R:R >= 2
    # f_rr's retest geometry is computed independently of f_history for any
    # ticker with at least this many weekly bars (needs swings + ATR14 + breakout)
    "retest_min_weekly_bars": 30,
    # smooth weekly streak
    "min_smooth_streak_weeks": 5,                        # f_smooth_streak
    "smooth_streak_cap_weeks": 104,
    "doji_max_body_frac": 0.10,                          # doji: body <= 10% of range
    "doji_min_close_pos": 0.40,                          # doji: close >= low + 40% of range
    # shape-only reversals (no zone gate)
    "daily_reversal_lookback_days": 10,                  # f_daily_reversal
    "weekly_reversal_lookback_weeks": 5,                 # f_weekly_reversal
    "reversal_kinds": ("hammer", "engulfing", "strong_close", "rejection"),
    # reversal candles count only AT the TV zone: low <= top + 0.5 ATR and (low >= bottom - 0.5 ATR
    # or close >= bottom); ATR(14) of the same timeframe (weekly / daily). No TV zone -> False
    "reversal_zone_atr": 0.5,
    # price near the TradingView support zone (TV drawings only; NOT part of status)
    "near_zone_atr_mult": 1.0,                           # f_near_zone: distance <= 1 x weekly ATR
    "near_zone_atr_period": 14,                          # weekly ATR(14), same ATR as the retest scan
    # obsolete-drawing check (informational, NOT part of status)
    "stale_far_atr": 3.0,                                # "far": latest close > zone top + 3 x weekly ATR
    # "broken" basis: "low" (default, user rule 2026-10-04) = ANY price below the SL, i.e. any
    # daily low (intraday wick) since the read date < SL; "daily" = any daily close < SL;
    # "weekly" = W-FRI weekly closes only (completed weeks + current week's latest close)
    "stale_close_basis": "low",
    # "technical" = clear weekly uptrend (informational, NOT part of status); port of
    # /workspace/drawing-learn/technical.py (calibrated on the user's 54 drawings)
    "tech_newhi_atr": 1.0,           # recent 26w high >= 1 ATR above the prior 2.5y high
    "tech_newhi_lookback_weeks": 130,  # prior-high window = weeks 27..130 back
    "tech_recent_weeks": 26,
    "tech_structure_weeks": 78,      # HH/HL swing window
    "tech_pivot_k": 3,               # swing clarity: 3 weeks each side
    "tech_structure_min": 0.5,       # (HH rate + HL rate) / 2 >= 0.5
    "tech_ema_span": 30,             # 30w EMA rising vs 26 weeks ago
    "tech_min_weekly_bars": 130,     # fewer bars -> f_technical empty (not enough history)
    # bot drawings (review needed): levels within max(0.011, 0.15% of the level) = same drawing
    "bot_match_rel": 0.0015,
    "bot_match_abs": 0.011,
}

CORE_FILTERS = [  # status=PASS iff all true
    "f_dollar_vol", "f_short_float", "f_no_earnings_14d", "f_history", "f_rr",
]
EXTRA_FILTERS = ["f_smooth_streak", "f_weekly_reversal", "f_daily_reversal"]
ALL_FILTERS = CORE_FILTERS + EXTRA_FILTERS

TV_COLS = ["tv_found", "tv_zone_top", "tv_zone_bottom", "tv_entry", "tv_sl", "tv_tp", "tv_rr", "tv_read_date",
           "tv_screenshot"]  # tv_screenshot = repo-relative chart image (charts/latest/<TICKER>.webp)
# price vs the TradingView zone (only for tv_found=yes; otherwise all empty, f_near_zone empty too)
NEAR_ZONE_COLS = ["tv_price", "tv_weekly_atr", "tv_zone_dist", "tv_zone_dist_atr"]
INFO_FILTERS = ["f_near_zone"]  # checkbox filters that may be null (not in status)
# obsolete-drawing check (tv_found=yes only): f_tv_stale True/False, tv_stale = "broken" /
# "target hit" / "far" (comma-joined when several), tv_stale_detail = numbers
STALE_COLS = ["f_tv_stale", "tv_stale", "tv_stale_detail"]
# technical = clear weekly uptrend (every row with >= tech_min_weekly_bars weekly bars; else empty)
TECH_COLS = ["f_technical", "tech_new_high_atr", "tech_hh", "tech_hl", "tech_structure",
             "tech_ema30_slope_pct", "tech_ema_rising", "tech_detail"]
# reversal evidence at the TV zone (compute_evidence; grade is computed live in the browser)
EVIDENCE_COLS = [
    "ev_pullback_high", "ev_pullback_high_date",
    "ev_first_reaction", "ev_first_reaction_detail",
    "ev_double_bottom", "ev_double_bottom_detail",
    "ev_ma_support", "ev_ma_support_mas", "ev_ma_support_detail",
    "ev_fib", "ev_fib_levels", "ev_fib_detail",
]
# drawing source: tv_source = user / bot / bot-approved / "" ; f_bot_review = bot drawing awaiting
# the user's approval (does NOT count toward f_rr / PASS / grok); tv_bot_status / tv_bot_note = detail
SOURCE_COLS = ["tv_source", "f_bot_review", "tv_bot_status", "tv_bot_note"]

REPORT_COLS = [
    "ticker", "status", "failed_filters",
    *CORE_FILTERS, "f_rr_computed", *EXTRA_FILTERS, *INFO_FILTERS, "needs_drawing",
    "current_price", "dollar_vol_30d", "avg_vol_30d", "short_float_pct", "inst_own_pct",
    "earnings_date", "days_to_earnings", "weekly_bars",
    "zone_lo", "zone_hi", "entry", "sl", "tp", "rr", "sl_atr_mult", "atr", "atrs_from_entry",
    *TV_COLS, *SOURCE_COLS, *NEAR_ZONE_COLS, *STALE_COLS, *TECH_COLS, *EVIDENCE_COLS,
    "smooth_streak_weeks",
    "weekly_reversal_kind", "weekly_reversal_date",
    "daily_reversal_kind", "daily_reversal_date",
    "smooth_pullback", "earnings_known", "earnings_blackout",
    "filter_notes", "tradingview_url", "finviz_url", "reason",
]

_REPO_DIR = Path("/workspace/publish-stock-retest-scanner")  # charts/latest/ lives here
FV_CACHE_DIR = Path("/workspace/cache")
UNIVERSE_JSON = Path("/workspace/stock_screen_universe.json")  # written by stock_screen.py
_KIND_KEY = {
    "hammer": "hammer",
    "engulfing": "engulfing",
    "strong_close": "strong_close_shape",
    "rejection": "long_lower_wick",
}


def _push_config_to_ssa() -> None:
    ssa.DOJI_MAX_BODY_FRAC = float(CONFIG["doji_max_body_frac"])
    ssa.DOJI_MIN_CLOSE_POS = float(CONFIG["doji_min_close_pos"])
    ssa.SMOOTH_STREAK_CAP_WEEKS = int(CONFIG["smooth_streak_cap_weeks"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _num(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        f = float(v)
    except Exception:
        return None
    return f if np.isfinite(f) else None


def _pct(v: Any) -> Optional[float]:
    f = _num(v)
    if f is None:
        return None
    return round(f * 100, 2) if f <= 1.5 else round(f, 2)


def _read_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def fv_cached(ticker: str) -> Dict[str, Any]:
    """FinViz quote cache (short float / inst own), ignoring TTL, no network."""
    return _read_json(FV_CACHE_DIR / f"fv_{ticker}.json")


def earn_cached(ticker: str) -> Optional[str]:
    d = _read_json(FV_CACHE_DIR / f"earn_{ticker.strip().upper()}.json")
    ed = d.get("earnings_date")
    return str(ed)[:10] if ed else None


def _exchange_from_tv(url: Any) -> str:
    import re

    m = re.search(r"symbol=([A-Z]+):", str(url or ""))
    return m.group(1) if m else "UNKNOWN"


def _as_of_ts(report_date: date) -> Optional[pd.Timestamp]:
    """None (=now) for today's report, else end of the report day in New York."""
    if report_date >= ss._local_today():
        return None
    return pd.Timestamp(f"{report_date.isoformat()} 23:59").tz_localize("America/New_York")


def _scan_reversals(bars: Optional[pd.DataFrame], lookback: int,
                    zone: Optional[Tuple[float, float]] = None) -> Tuple[bool, str, str]:
    """Reversal-shape candle on any of the last `lookback` completed bars that is AT the zone
    (user rule 2026-10-09). zone = (bottom, top) of the TradingView rectangle; the bar's own ATR(14)
    on the same timeframe (weekly ATR for weekly bars, daily ATR for daily bars):
      Low <= top + reversal_zone_atr (0.5) x ATR   (inside the zone or at most 0.5 ATR above it)
      AND (Low >= bottom - 0.5 x ATR  OR  Close >= bottom)  (a wick under the zone counts when it
      closed back at/above the bottom, or stayed within 0.5 ATR below it).
    zone None -> no candle qualifies (no TV zone, no reversal at the zone).
    Returns (hit, kind, date) of the MOST RECENT matching bar."""
    if bars is None or len(bars) < 2 or zone is None:
        return False, "", ""
    zb, zt = min(zone), max(zone)
    m = float(CONFIG["reversal_zone_atr"])
    atr = ss.atr_series(bars, 14)
    kinds = [k for k in CONFIG["reversal_kinds"] if k in _KIND_KEY]
    n = len(bars)
    for i in range(n - 1, max(0, n - int(lookback)) - 1, -1):
        if i < 1:
            break
        a_i = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else float("nan")
        lo_i, cl_i = float(bars["Low"].iloc[i]), float(bars["Close"].iloc[i])
        if not np.isfinite(a_i) or not (lo_i <= zt + m * a_i and (lo_i >= zb - m * a_i or cl_i >= zb)):
            continue
        sh = ssa.weekly_reversal_shapes(
            float(bars["Open"].iloc[i]), float(bars["High"].iloc[i]),
            float(bars["Low"].iloc[i]), float(bars["Close"].iloc[i]),
            float(bars["Open"].iloc[i - 1]), float(bars["Close"].iloc[i - 1]),
            float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else float("nan"),
        )
        for k in kinds:
            if sh[_KIND_KEY[k]]:
                return True, k, str(pd.Timestamp(bars.index[i]).date())
    return False, "", ""


# ---------------------------------------------------------------------------
# per-row computation
# ---------------------------------------------------------------------------
def compute_row(
    ticker: str,
    daily_raw: Optional[pd.DataFrame],
    report_date: date,
    short_float_pct: Optional[float] = None,
    earnings_date: Optional[str] = None,
    exchange: str = "UNKNOWN",
    tv_rec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute every filter + value for one ticker independently.

    tv_rec = latest stored TradingView drawing reading for the ticker (or None).
    """
    C = CONFIG
    notes: List[str] = []
    r: Dict[str, Any] = {c: None for c in REPORT_COLS}
    r["ticker"] = ticker
    for f in ALL_FILTERS:
        r[f] = False
    r["f_rr_computed"] = False
    r["smooth_pullback"] = False
    r["weekly_reversal_kind"] = r["daily_reversal_kind"] = ""
    r["weekly_reversal_date"] = r["daily_reversal_date"] = ""

    # --- short float ------------------------------------------------------
    r["short_float_pct"] = short_float_pct
    if short_float_pct is None:
        notes.append("short float N/A")
    else:
        r["f_short_float"] = bool(short_float_pct < C["short_float_max_pct"])

    # --- earnings ---------------------------------------------------------
    if earnings_date:
        try:
            ed = date.fromisoformat(str(earnings_date)[:10])
            dte = (ed - report_date).days
            r["earnings_date"] = ed.isoformat()
            if dte < 0:
                notes.append(f"earnings date stale ({ed.isoformat()})")
                r["earnings_known"] = False
                r["earnings_blackout"] = False
            else:
                r["days_to_earnings"] = int(dte)
                r["earnings_known"] = True
                r["earnings_blackout"] = bool(dte < C["earnings_blackout_days"])
                r["f_no_earnings_14d"] = not r["earnings_blackout"]
        except Exception:
            notes.append("earnings date unparseable")
    else:
        notes.append("earnings unknown")
    if r["earnings_known"] is None:
        r["earnings_known"] = False
        r["earnings_blackout"] = False

    # --- price history ----------------------------------------------------
    need = ["Open", "High", "Low", "Close", "Volume"]
    daily = None
    if daily_raw is not None and not getattr(daily_raw, "empty", True) and all(
        c in daily_raw.columns for c in need
    ):
        daily = ss._normalize_ohlcv_index(daily_raw)
        daily = daily[daily.index.normalize() <= pd.Timestamp(report_date)]
        hist = daily[need].dropna()
    else:
        hist = None
    if hist is None or len(hist) < 2:
        notes.append("no price history")
        apply_tv(r, tv_rec)
        apply_source(r, ticker, tv_rec)
        r["filter_notes"] = "; ".join(notes)
        return r

    last_close = float(hist["Close"].iloc[-1])
    avg_vol = float(hist["Volume"].tail(C["avg_vol_days"]).mean())
    r["current_price"] = last_close
    r["avg_vol_30d"] = avg_vol
    r["dollar_vol_30d"] = last_close * avg_vol
    r["f_dollar_vol"] = bool(r["dollar_vol_30d"] >= C["dollar_vol_min"])

    weekly = ss.to_weekly(hist)  # screen's weekly bars (same as the retest scan)
    r["weekly_bars"] = int(len(weekly))
    r["f_history"] = bool(len(weekly) >= C["min_weekly_bars"])

    # --- f_rr: retest geometry (zone -> entry/SL/TP) AND R:R ----------------
    setup = None
    if len(weekly) >= C["retest_min_weekly_bars"]:
        try:
            setup = ss.weekly_retest_setup(weekly, min_bars=C["retest_min_weekly_bars"])
        except Exception as e:  # pragma: no cover
            notes.append(f"retest error: {e}")
    else:
        notes.append(f"too few weekly bars for computed retest ({len(weekly)})")
    if setup is not None:
        for k in ("zone_lo", "zone_hi", "entry", "sl", "tp", "rr", "atr"):
            r[k] = float(setup[k])
        atr = r["atr"]
        r["atrs_from_entry"] = (last_close - r["entry"]) / atr if atr else None
        r["f_rr_computed"] = bool(r["rr"] >= C["rr_min"])
        if atr and atr > 0:  # informational: SL distance in ATR (setup clamps to 0.5-1.0)
            r["sl_atr_mult"] = (r["entry"] - r["sl"]) / atr
    elif len(weekly) >= C["retest_min_weekly_bars"]:
        notes.append("no computed weekly retest setup")

    # --- f_rr: the user's TradingView drawing (read-only) ------------------
    apply_tv(r, tv_rec)
    apply_source(r, ticker, tv_rec)
    if not r["f_rr"]:
        notes.append(tv_note(r))
    r.update(compute_near_zone(hist, r))
    r.update({k: v for k, v in compute_stale(hist, r).items() if k in STALE_COLS})
    r.update(compute_technical(hist))
    r.update(compute_evidence(hist, r))

    # --- smooth streak / reversals (completed bars only) --------------------
    as_of = _as_of_ts(report_date)
    try:
        st = ssa.compute_smooth_streak(daily, as_of=as_of, cap=int(C["smooth_streak_cap_weeks"]))
        r["smooth_streak_weeks"] = st["smooth_streak_weeks"]
        if st["smooth_streak_weeks"] is not None:
            r["f_smooth_streak"] = bool(st["smooth_streak_weeks"] >= C["min_smooth_streak_weeks"])
    except Exception as e:  # pragma: no cover
        notes.append(f"streak error: {e}")
    try:
        r.update(compute_reversals(daily, report_date, r))
    except Exception as e:  # pragma: no cover
        notes.append(f"reversal error: {e}")

    # --- informational smooth_pullback (needs a zone) -----------------------
    if setup is not None:
        try:
            a = ssa.analyze_one(exchange, ticker, daily, zone_lo=r["zone_lo"], zone_hi=r["zone_hi"])
            r["smooth_pullback"] = a.get("verdict") == "STRONG"
        except Exception as e:  # pragma: no cover
            notes.append(f"smooth_pullback error: {e}")

    r["filter_notes"] = "; ".join(notes)
    return r


REVERSAL_COLS = ["f_weekly_reversal", "weekly_reversal_kind", "weekly_reversal_date",
                 "f_daily_reversal", "daily_reversal_kind", "daily_reversal_date"]


def compute_reversals(daily: Optional[pd.DataFrame], report_date: date, r: Dict[str, Any]) -> Dict[str, Any]:
    """E1 / E2: reversal-shape candle AT the TV zone (see _scan_reversals) on the last
    weekly_reversal_lookback_weeks (5) completed weekly bars / daily_reversal_lookback_days (10)
    completed daily bars. Uses r's tv_zone_top / tv_zone_bottom (tv_found=yes); no zone -> False."""
    C = CONFIG
    out = {"f_weekly_reversal": False, "weekly_reversal_kind": "", "weekly_reversal_date": "",
           "f_daily_reversal": False, "daily_reversal_kind": "", "daily_reversal_date": ""}
    if daily is None or len(daily) < 2:
        return out
    zone = None
    if str(r.get("tv_found")) == "yes":
        top, bot = _num(r.get("tv_zone_top")), _num(r.get("tv_zone_bottom"))
        if top is not None and bot is not None:
            zone = (bot, top)
    dd = ssa.flatten_cols(daily)
    dd = ssa.completed_daily_bars(dd, as_of=_as_of_ts(report_date))
    wk = ssa.completed_weeks(ssa.to_weekly(dd), dd.index[-1])
    hit, kind, dt = _scan_reversals(wk, C["weekly_reversal_lookback_weeks"], zone)
    out["f_weekly_reversal"], out["weekly_reversal_kind"], out["weekly_reversal_date"] = hit, kind, dt
    hit, kind, dt = _scan_reversals(dd, C["daily_reversal_lookback_days"], zone)
    out["f_daily_reversal"], out["daily_reversal_kind"], out["daily_reversal_date"] = hit, kind, dt
    return out


def apply_tv(r: Dict[str, Any], rec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fill tv_* from a stored reading and set f_rr = found AND tv_rr >= rr_min."""
    for c in TV_COLS:
        r[c] = ""
    if rec:
        r["tv_read_date"] = rec.get("read_date") or ""
        if rec.get("found"):
            r["tv_found"] = "yes"
            for k in ("zone_top", "zone_bottom", "entry", "sl", "tp", "rr"):
                v = _num(rec.get(k))
                r[f"tv_{k}"] = "" if v is None else f"{v:g}"
        else:
            r["tv_found"] = "no"
        shot = rec.get("screenshot") or ""  # found or not-found reads both keep a screenshot
        r["tv_screenshot"] = shot if shot and (_REPO_DIR / shot).exists() else ""
    rr = _num(rec.get("rr")) if rec and rec.get("found") else None
    r["f_rr"] = bool(rr is not None and rr >= CONFIG["rr_min"])
    return r


def compute_near_zone(hist: Optional[pd.DataFrame], r: Dict[str, Any]) -> Dict[str, Any]:
    """Price vs the TradingView zone (tv_found=yes rows only; else every value is None).

    price = latest daily close in `hist` (daily bars already cut at the report date);
    weekly ATR = stock_screen.atr_series(to_weekly(hist), 14) last value (W-FRI bars,
    the same weekly ATR(14) the retest scan uses; the report-date week may be partial);
    dist = 0 inside [zone_bottom, zone_top], else distance to the nearest edge;
    f_near_zone = dist <= near_zone_atr_mult x weekly ATR.
    """
    out: Dict[str, Any] = {c: None for c in NEAR_ZONE_COLS + ["f_near_zone"]}
    if str(r.get("tv_found")) != "yes" or hist is None or len(hist) == 0:
        return out
    top, bot = _num(r.get("tv_zone_top")), _num(r.get("tv_zone_bottom"))
    if top is None or bot is None:
        return out
    if bot > top:
        top, bot = bot, top
    price = float(hist["Close"].iloc[-1])
    out["tv_price"] = round(price, 4)
    atr = None
    try:
        a = ss.atr_series(ss.to_weekly(hist), int(CONFIG["near_zone_atr_period"])).dropna()
        atr = float(a.iloc[-1]) if len(a) else None
    except Exception:
        atr = None
    dist = 0.0 if bot <= price <= top else (price - top if price > top else bot - price)
    out["tv_zone_dist"] = round(dist, 4)
    if atr and atr > 0:
        out["tv_weekly_atr"] = round(atr, 4)
        out["tv_zone_dist_atr"] = round(dist / atr, 4)
        out["f_near_zone"] = bool(dist <= float(CONFIG["near_zone_atr_mult"]) * atr)
    return out


def compute_stale(hist: Optional[pd.DataFrame], r: Dict[str, Any]) -> Dict[str, Any]:
    """Has a TradingView drawing gone obsolete? (tv_found=yes rows only; else all None)

    hist = cached daily OHLCV already cut at the as-of date. Flags (all that apply):
      broken     - ANY price below the drawn SL since the read date. stale_close_basis:
                   "low" (default) any daily low (intraday wick) < SL; "daily" any daily
                   close < SL; "weekly" only W-FRI weekly closes (completed weeks + the
                   current week's latest close). The latest close < SL always counts.
                   Prices that dip below the zone but stay above the SL do NOT break it.
      target hit - latest close >= drawn TP.
      far        - latest close > zone top + stale_far_atr (3) x weekly ATR(14).
    """
    out: Dict[str, Any] = {"f_tv_stale": None, "tv_stale": None, "tv_stale_detail": None,
                           "latest_close": None, "last_bar": None, "weekly_atr": None,
                           "dist_above_top_atr": None}
    if str(r.get("tv_found")) != "yes" or hist is None or len(hist) == 0:
        return out
    top, sl, tp = _num(r.get("tv_zone_top")), _num(r.get("tv_sl")), _num(r.get("tv_tp"))
    price = float(hist["Close"].iloc[-1])
    out["latest_close"] = round(price, 4)
    out["last_bar"] = pd.Timestamp(hist.index[-1]).date().isoformat()
    weekly = ss.to_weekly(hist)
    atr = None
    try:
        a = ss.atr_series(weekly, int(CONFIG["near_zone_atr_period"])).dropna()
        atr = float(a.iloc[-1]) if len(a) else None
    except Exception:
        atr = None
    out["weekly_atr"] = None if atr is None else round(atr, 4)
    flags, detail = [], []
    if sl is not None:
        basis = str(CONFIG.get("stale_close_basis", "low"))
        if basis not in ("low", "daily", "weekly"):
            basis = "low"
        bars = weekly if basis == "weekly" else hist
        col = "Low" if basis == "low" else "Close"
        kind, plural = {"low": ("low", "lows"), "daily": ("close", "closes"),
                        "weekly": ("weekly close", "weekly closes")}[basis]
        try:
            rd = pd.Timestamp(str(r.get("tv_read_date"))[:10])
            # daily: sessions on/after the read date; weekly: W-FRI bars ending on/after it
            win = bars[bars.index.normalize() >= rd]
        except Exception:
            win = bars.iloc[-1:]
        below = win[win[col] < sl]
        if len(below) or price < sl:
            flags.append("broken")
            if len(below):
                d0 = pd.Timestamp(below.index[0]).date().isoformat()
                lo = below[col].idxmin()
                detail.append(f"{kind} {float(below[col].iloc[0]):.2f} < SL {sl:g} on {d0}"
                              + (f" ({len(below)} {plural} below, lowest {float(below[col].min()):.2f} on "
                                 f"{pd.Timestamp(lo).date().isoformat()})" if len(below) > 1 else ""))
            else:
                detail.append(f"close {price:.2f} < SL {sl:g}")
    if tp is not None and price >= tp:
        flags.append("target hit")
        detail.append(f"close {price:.2f} >= TP {tp:g}")
    if top is not None and atr and atr > 0:
        dist = (price - top) / atr
        out["dist_above_top_atr"] = round(dist, 4)
        if dist > float(CONFIG["stale_far_atr"]):
            flags.append("far")
            detail.append(f"close {price:.2f} is {dist:.2f} ATR above zone top {top:g}")
    out["f_tv_stale"] = bool(flags)
    out["tv_stale"] = ", ".join(flags)
    out["tv_stale_detail"] = "; ".join(detail)
    return out


# ---------------------------------------------------------------------------
# technical = clear weekly uptrend (port of /workspace/drawing-learn/technical.py)
# ---------------------------------------------------------------------------
def _swing_pivots(a: np.ndarray, k: int, kind: str) -> List[int]:
    return [i for i in range(k, len(a) - k)
            if (kind == "hi" and a[i] > max(np.r_[a[i - k:i], a[i + 1:i + k + 1]]))
            or (kind == "lo" and a[i] < min(np.r_[a[i - k:i], a[i + 1:i + k + 1]]))]


def compute_technical(hist: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """'Technical' = clear weekly uptrend (all three, W-FRI weekly bars from the cached daily
    history cut at the report date; the current week may be partial):
      1. NEW HIGH: recent high (max High of the last 26 weeks) >= 1.0 weekly ATR(14) above the
         highest High of the 2.5 years before it (weeks 27-130 back).
      2. STRUCTURE: over the last 78 weeks, with strength-3 swing pivots (3 weeks each side),
         (share of higher highs + share of higher lows) / 2 >= 0.5. The recent high counts as
         the latest swing high; swing lows after it (the current pullback) are ignored.
      3. TREND: 30-week EMA higher than 26 weeks ago (price may be below it in the pullback).
    Fewer than tech_min_weekly_bars weekly bars -> every column empty. Informational only.
    """
    C = CONFIG
    out: Dict[str, Any] = {c: None for c in TECH_COLS}
    if hist is None or len(hist) < 2:
        return out
    try:
        w = ss.to_weekly(hist)
        n = len(w)
        if n < int(C["tech_min_weekly_bars"]):
            out["tech_detail"] = f"not enough history ({n} weekly bars < {int(C['tech_min_weekly_bars'])})"
            return out
        h, l, c = (w[x].values.astype(float) for x in ("High", "Low", "Close"))
        atr = float(ss.atr_series(w).iloc[-1])
        rw, k = int(C["tech_recent_weeks"]), int(C["tech_pivot_k"])
        ihi = n - rw + int(np.argmax(h[-rw:]))
        rh = float(h[ihi])
        prior = float(h[max(0, n - int(C["tech_newhi_lookback_weeks"])):n - rw].max())
        newhi = (rh - prior) / atr
        i0 = max(0, n - int(C["tech_structure_weeks"]))
        ph = sorted(set([i for i in _swing_pivots(h, k, "hi") if i >= i0] + [ihi]))
        pl = [i for i in _swing_pivots(l, k, "lo") if i0 <= i < ihi]
        hh = int(sum(h[b] > h[a] for a, b in zip(ph, ph[1:])))
        nh = max(1, len(ph) - 1)
        hl = int(sum(l[b] > l[a] for a, b in zip(pl, pl[1:])))
        nl = max(1, len(pl) - 1)
        struct = (hh / nh + hl / nl) / 2
        ema = pd.Series(c).ewm(span=int(C["tech_ema_span"]), adjust=False).mean().values
        slope = (ema[-1] / ema[-27] - 1) * 100
    except Exception as e:  # pragma: no cover
        out["tech_detail"] = f"technical error: {e}"
        return out
    ok1, ok2, ok3 = newhi >= float(C["tech_newhi_atr"]), struct >= float(C["tech_structure_min"]), slope > 0
    tech = bool(ok1 and ok2 and ok3)
    if tech:
        why = [f"uptrend: new high {newhi:+.1f} ATR above prior 2.5y high, {hh}/{nh} HH and {hl}/{nl} HL, "
               f"30w EMA {slope:+.0f}% in 26w"]
    else:
        why = []
        if not ok1:
            why.append(f"no new high: recent high {rh:.2f} is {newhi:+.2f} ATR vs prior 2.5y high {prior:.2f} "
                       f"(needs >= +{float(C['tech_newhi_atr']):g})")
        if not ok2:
            why.append(f"choppy swings: {hh}/{nh} higher highs, {hl}/{nl} higher lows")
        if not ok3:
            why.append(f"30w EMA falling ({slope:+.0f}% in 26w)")
    out.update({"f_technical": tech, "tech_new_high_atr": round(newhi, 2), "tech_hh": f"{hh}/{nh}",
                "tech_hl": f"{hl}/{nl}", "tech_structure": round(struct, 2),
                "tech_ema30_slope_pct": round(slope, 1), "tech_ema_rising": bool(ok3),
                "tech_detail": "; ".join(why)})
    return out


# ---------------------------------------------------------------------------
# reversal evidence at the TradingView zone (grade A/B/C/D is computed live in the browser)
# ---------------------------------------------------------------------------
# E3 ev_first_reaction, E4 ev_double_bottom, E8 ev_fib need a TV zone (tv_found=yes with zone
# top/bottom; else empty). E7 ev_ma_support needs only price history (every row with enough
# daily bars). E1/E2 = f_weekly_reversal / f_daily_reversal, E5 = smooth_streak_weeks >= N,
# E6 = tv_rr >= X are existing columns (thresholds N / X are browser inputs).
EVIDENCE_CONFIG: Dict[str, Any] = {
    "ev_pullback_lookback_weeks": 52,     # pullback high = highest weekly High in the last 52 weeks
    "ev_first_reaction_atr": 0.5,         # E3: later weekly close >= zone top + 0.5 weekly ATR
    "ev_dbl_push_atr": 1.0,               # E4: push up = daily High >= zone top + 1 daily ATR
    "ev_dbl_recent_days": 10,             # E4: 2nd touch within the last 10 sessions ...
    "ev_dbl_near_atr": 1.0,               # E4: ... or latest close within 1 daily ATR of the zone
    "ev_ma_periods": (50, 100, 150, 200), # E7: daily SMAs
    "ev_ma_near_atr": 1.0,                # E7: latest low <= SMA + 1 daily ATR and close >= SMA
    "ev_ma_past_sessions": 504,           # E7: earlier touches in the past ~2 years ...
    "ev_ma_exclude_recent": 20,           # ... excluding the last 20 sessions (the current touch)
    "ev_ma_bounce_atr": 2.0,              # ... that rose >= 2 daily ATR above the SMA ...
    "ev_ma_bounce_sessions": 20,          # ... within 20 sessions
    "ev_ma_cooldown": 10,                 # touches < 10 sessions apart = one touch
    "ev_fib_levels": (0.382, 0.5, 0.618), # E8 retracements
    "ev_fib_leg_weeks": 52,               # E8: swing low = lowest weekly Low in the 52 weeks up to the swing high
    "ev_fib_tol_atr": 0.25,               # E8: level inside [zone bottom - 0.25 wATR, zone top + 0.25 wATR]
}
CONFIG.update(EVIDENCE_CONFIG)


def _sma_touch_events(lo: np.ndarray, cl: np.ndarray, sma: np.ndarray, atr: np.ndarray,
                      start: int, end: int) -> List[int]:
    """Earlier MA-support touches in [start, end): price came from above (previous close above
    the SMA), the day's low came within near_atr x ATR of the SMA or below it (low <= SMA + near
    ATR), the close held (close >= SMA), the low is a local low (lowest low of +/- 5 sessions), and
    within bounce_sessions a close rose >= bounce_atr x ATR above the touch day's SMA. Touches
    closer than `cooldown` sessions count once."""
    C = CONFIG
    near, up, win, cool = (float(C["ev_ma_near_atr"]), float(C["ev_ma_bounce_atr"]),
                           int(C["ev_ma_bounce_sessions"]), int(C["ev_ma_cooldown"]))
    ev, last = [], -10 ** 9
    for t in range(max(start, 1), end):
        s, a = sma[t], atr[t]
        if not (np.isfinite(s) and np.isfinite(a) and a > 0 and np.isfinite(sma[t - 1])):
            continue
        if t - last < cool or cl[t - 1] <= sma[t - 1]:
            continue
        if lo[t] <= s + near * a and cl[t] >= s and lo[t] <= float(np.min(lo[max(0, t - 5):t + 6])):
            fut = cl[t + 1:t + 1 + win]
            if len(fut) and float(np.max(fut)) >= s + up * a:
                ev.append(t)
                last = t
    return ev


def compute_evidence(hist: Optional[pd.DataFrame], r: Dict[str, Any]) -> Dict[str, Any]:
    """Reversal evidence at the TradingView zone (see RULES.md "Grades").

    hist = cached daily OHLCV cut at the report date; weekly = W-FRI bars (current week may be
    partial); weekly ATR = ATR(14) on weekly bars, daily ATR = ATR(14) on daily bars (latest).
    Pullback high = the bar with the highest weekly High in the last 52 weeks; the current
    pullback = everything after it.
      E3 first reaction: a pullback week (after the high week) with Low <= zone top, followed by a
         LATER week whose Close >= zone top + 0.5 weekly ATR.
      E4 daily double bottom: after the pullback high, a 1st daily touch (Low <= zone top), then a
         push (a later daily High >= zone top + 1 daily ATR), then a 2nd touch after the push:
         a daily Low <= zone top within the last 10 sessions, OR the latest close within 1 daily
         ATR of the zone (dist to [bottom, top] <= 1 ATR); and the latest close is not below
         zone bottom - 1 daily ATR (not broken down).
      E7 MA support (no zone needed): for SMA 50/100/150/200 (daily closes), the latest daily low is
         <= SMA + 1 daily ATR (within 1 ATR above it, or below it) AND the latest close >= SMA (held),
         AND the same SMA held before: >= 1 earlier touch in the 504 sessions before the last 20
         (see _sma_touch_events).
      E8 fib: swing high = pullback high; swing low = lowest weekly Low in the 52 weeks up to (and
         incl.) the swing-high week; a 0.382 / 0.5 / 0.618 retracement H - f x (H - L) lies inside
         [zone bottom - 0.25 weekly ATR, zone top + 0.25 weekly ATR].
    """
    C = CONFIG
    out: Dict[str, Any] = {c: None for c in EVIDENCE_COLS}
    if hist is None or len(hist) < 30:
        return out
    try:
        d = hist[["Open", "High", "Low", "Close"]].astype(float)
        lo, hi, cl = d["Low"].values, d["High"].values, d["Close"].values
        datr = ss.atr_series(d, 14).values
        a_d = float(datr[-1]) if np.isfinite(datr[-1]) else None
        n = len(d)
        # --- E7 MA support (every row) ------------------------------------------
        mas, det = [], []
        if a_d and a_d > 0:
            past_end = n - int(C["ev_ma_exclude_recent"])
            past_start = max(1, n - int(C["ev_ma_past_sessions"]) - int(C["ev_ma_exclude_recent"]))
            for p in C["ev_ma_periods"]:
                p = int(p)
                if n < p + 30:
                    continue
                sma = pd.Series(cl).rolling(p, min_periods=p).mean().values
                s = float(sma[-1])
                # reached as support: latest low within 1 daily ATR above the SMA (or below it), close held >= SMA
                near = lo[-1] <= s + float(C["ev_ma_near_atr"]) * a_d and cl[-1] >= s
                if not near:
                    continue
                ev = _sma_touch_events(lo, cl, sma, datr, past_start, past_end)
                if ev:
                    mas.append(f"SMA{p}")
                    det.append(f"SMA{p} {s:.2f} (latest low {lo[-1]:.2f} / close {cl[-1]:.2f}); held before "
                               f"{len(ev)}x, last {pd.Timestamp(d.index[ev[-1]]).date().isoformat()}")
            out["ev_ma_support"] = bool(mas)
            out["ev_ma_support_mas"] = ",".join(mas)
            out["ev_ma_support_detail"] = "; ".join(det) if det else "no SMA50/100/150/200 support with an earlier bounce"
        # --- zone-based evidence (TV drawings with a zone only) -------------------
        if str(r.get("tv_found")) != "yes":
            return out
        top, bot = _num(r.get("tv_zone_top")), _num(r.get("tv_zone_bottom"))
        if top is None or bot is None:
            return out
        if bot > top:
            top, bot = bot, top
        w = ss.to_weekly(d.assign(Volume=0.0))
        watr_s = ss.atr_series(w, 14).dropna()
        if len(w) < 20 or not len(watr_s) or not a_d:
            return out
        a_w = float(watr_s.iloc[-1])
        lb = int(C["ev_pullback_lookback_weeks"])
        w0 = max(0, len(w) - lb)
        ih = w0 + int(np.argmax(w["High"].values[w0:]))
        H = float(w["High"].iloc[ih])
        hdate = pd.Timestamp(w.index[ih])
        out["ev_pullback_high"] = round(H, 4)
        out["ev_pullback_high_date"] = hdate.date().isoformat()
        # E3 first reaction (weekly)
        wl, wc = w["Low"].values, w["Close"].values
        thr = top + float(C["ev_first_reaction_atr"]) * a_w
        fr, frd = False, f"no weekly low <= zone top {top:g} since the {hdate.date()} high"
        for i in range(ih + 1, len(w)):
            if wl[i] <= top:
                later = [j for j in range(i + 1, len(w)) if wc[j] >= thr]
                if later:
                    j = later[0]
                    fr = True
                    frd = (f"week {pd.Timestamp(w.index[i]).date()} low {wl[i]:.2f} <= zone top {top:g}; "
                           f"week {pd.Timestamp(w.index[j]).date()} close {wc[j]:.2f} >= {thr:.2f} (top + "
                           f"{float(C['ev_first_reaction_atr']):g} wATR {a_w:.2f})")
                    break
                frd = (f"entered zone week {pd.Timestamp(w.index[i]).date()} (low {wl[i]:.2f}) but no later "
                       f"weekly close >= {thr:.2f}")
        out["ev_first_reaction"], out["ev_first_reaction_detail"] = fr, frd
        # E4 daily double bottom (after the pullback-high week starts)
        wk_start = hdate - pd.Timedelta(days=6)
        di = np.where(d.index >= wk_start)[0]
        db, dbd = False, "no daily touch of the zone in the pullback"
        if len(di):
            s0 = int(di[0])
            # skip the days before the pullback high day itself
            s0 = s0 + int(np.argmax(hi[s0:])) if n - s0 > 0 else s0
            push_thr = top + float(C["ev_dbl_push_atr"]) * a_d
            t1 = next((t for t in range(s0, n) if lo[t] <= top), None)
            if t1 is not None:
                tp_ = next((t for t in range(t1 + 1, n) if hi[t] >= push_thr), None)
                if tp_ is None:
                    dbd = f"1st touch {d.index[t1].date()} (low {lo[t1]:.2f}), no push to {push_thr:.2f} yet"
                else:
                    recent = int(C["ev_dbl_recent_days"])
                    t2 = [t for t in range(max(tp_ + 1, n - recent), n) if lo[t] <= top]
                    p = cl[-1]
                    dist = 0.0 if bot <= p <= top else (p - top if p > top else bot - p)
                    near = dist <= float(C["ev_dbl_near_atr"]) * a_d and n - 1 > tp_
                    broken = p < bot - a_d
                    if (t2 or near) and not broken:
                        db = True
                        second = (f"2nd touch {d.index[t2[-1]].date()} low {lo[t2[-1]]:.2f}" if t2
                                  else f"close {p:.2f} within {dist / a_d:.2f} dATR of the zone")
                        dbd = (f"1st touch {d.index[t1].date()} low {lo[t1]:.2f}; push {d.index[tp_].date()} "
                               f"high {hi[tp_]:.2f} >= {push_thr:.2f}; {second}")
                    elif broken:
                        dbd = f"close {p:.2f} below zone bottom - 1 dATR (broken down)"
                    else:
                        dbd = (f"1st touch {d.index[t1].date()}, push {d.index[tp_].date()}; no 2nd touch "
                               f"in the last {recent} sessions and close {p:.2f} is {dist / a_d:.2f} dATR from the zone")
        out["ev_double_bottom"], out["ev_double_bottom_detail"] = db, dbd
        # E8 fib confluence
        l0 = max(0, ih - int(C["ev_fib_leg_weeks"]) + 1)
        il = l0 + int(np.argmin(wl[l0:ih + 1]))
        L = float(wl[il])
        tol = float(C["ev_fib_tol_atr"]) * a_w
        hits, lv = [], []
        if H > L:
            for f in C["ev_fib_levels"]:
                x = H - float(f) * (H - L)
                lv.append(f"{float(f):g}={x:.2f}")
                if bot - tol <= x <= top + tol:
                    hits.append(f"{float(f):g}")
        out["ev_fib"] = bool(hits)
        out["ev_fib_levels"] = ",".join(hits)
        out["ev_fib_detail"] = (f"swing {L:.2f} ({pd.Timestamp(w.index[il]).date()}) -> {H:.2f} ({hdate.date()}): "
                                f"{', '.join(lv)}; zone {bot:g}-{top:g} +/- {tol:.2f}")
    except Exception as e:  # pragma: no cover
        out["ev_fib_detail"] = f"evidence error: {e}"
    return out


# ---------------------------------------------------------------------------
# drawing source: user vs bot (bot drawings need the user's approval before they count)
# ---------------------------------------------------------------------------
BOT_REGISTRY = Path("/workspace/stock-screener/bot_drawings.json")         # {"tickers": {T: {...}}}
BOT_APPROVED = Path("/workspace/stock-screener/approved_bot_drawings.json")  # {"approved": {T: {...}}}
BOT_LABEL_RE = re.compile(r"\bBOT\b.*review", re.I)
_LEVEL_KEYS = ("zone_top", "zone_bottom", "entry", "sl", "tp")
_REG_CACHE: Dict[str, Any] = {}


def _load_cached_json(p: Path, key: str) -> Dict[str, Any]:
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}
    c = _REG_CACHE.get(str(p))
    if c and c[0] == m:
        return c[1]
    d = _read_json(p).get(key, {}) or {}
    d = {str(t).strip().upper(): v for t, v in d.items()}
    _REG_CACHE[str(p)] = (m, d)
    return d


def load_bot_registry() -> Dict[str, Dict[str, Any]]:
    return _load_cached_json(BOT_REGISTRY, "tickers")


def load_bot_approved() -> Dict[str, Dict[str, Any]]:
    return _load_cached_json(BOT_APPROVED, "approved")


def levels_match(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> bool:
    """Near-identical zone / entry / SL / TP (each within max(bot_match_abs, bot_match_rel x level))."""
    if not a or not b:
        return False
    for k in _LEVEL_KEYS:
        x, y = _num(a.get(k)), _num(b.get(k))
        if x is None or y is None:
            return False
        if abs(x - y) > max(float(CONFIG["bot_match_abs"]), float(CONFIG["bot_match_rel"]) * abs(y)):
            return False
    return True


def drawing_source(ticker: str, rec: Optional[Dict[str, Any]],
                   registry: Optional[Dict[str, Dict[str, Any]]] = None,
                   approved: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Who owns the ticker's TradingView drawing.

    rec = latest stored read (tv_drawings.json); registry = bot_drawings.json (levels the bot
    drew); approved = approved_bot_drawings.json. Rules:
      - read found + levels near-identical to the registry entry -> bot (also when the read's
        rectangle text was "BOT - review needed"); explicit `upsert --source user` -> user;
        found but levels changed vs the registry -> user (the user edited it = user-owned);
        found, no registry entry -> user (unless the read itself says source bot).
      - not found / never read, registry entry with levels, read older than the bot drawing ->
        bot ("bot drawing - awaiting nightly read"); a not-found read AFTER the bot drew it -> "" with
        status "bot drawing missing on chart" (counts as needs drawing again).
      - registry entry without levels (data issue) -> status "needs manual drawing (data issue)".
      - bot + approved (approved entry without levels, or levels matching) -> bot-approved
        (counts like a user drawing). f_bot_review = tv_source == "bot".
    """
    t = str(ticker).strip().upper()
    registry = load_bot_registry() if registry is None else registry
    approved = load_bot_approved() if approved is None else approved
    b = registry.get(t)
    found = bool(rec and rec.get("found"))
    override = str((rec or {}).get("source_override") or "")
    src, status, note = ("user" if found else ""), "", ""
    if found:  # partial user drawings: no rectangle / no Long Position / short only / values pending
        status, note = str(rec.get("drawing_status") or ""), str(rec.get("drawing_note") or "")
    if rec and not found and rec.get("lines_only"):
        # the user's own chart has only Fib / horizontal lines: not needs drawing, not a bot drawing
        return {"tv_source": "user-lines", "f_bot_review": False,
                "tv_bot_status": "user lines only, no zone/position",
                "tv_bot_note": str(rec.get("drawing_note") or "user lines only (Fib / horizontal lines), no zone or position")}
    if b and not b.get("has_level", True):
        status = "needs manual drawing (data issue)"
        note = f"needs manual drawing (data issue): {b.get('reason') or 'no bot level'}"
    elif b:
        lv = (f"zone {b.get('zone_bottom')}-{b.get('zone_top')} entry {b.get('entry')} SL {b.get('sl')} "
              f"TP {b.get('tp')} R:R {b.get('rr')}")
        if found:
            if override == "user":
                src, status, note = "user", "user-owned (marked)", f"bot drawing marked user-owned ({lv})"
            elif levels_match(rec, b):
                src, status = "bot", "bot drawing on chart"
                note = f"bot drawing (review needed): {lv}"
            else:
                src, status = "user", "user-edited bot drawing"
                note = f"levels changed vs the bot drawing ({lv}) -> user-owned"
        else:
            drawn = str(b.get("drawn_at") or b.get("registered_at") or "")
            read = str((rec or {}).get("read_at") or "")
            if rec and read and drawn and read > drawn and override != "bot":
                src, status = "", "bot drawing missing on chart"
                note = f"read {rec.get('read_date')} found no drawing after the bot drew it ({lv})"
            else:
                src, status = "bot", "bot drawing - awaiting nightly read"
                note = f"bot drawing (review needed, awaiting nightly read): {lv}"
    elif found and (override == "bot" or str((rec or {}).get("source") or "") == "bot"):
        src, status, note = "bot", "bot drawing on chart", "bot drawing (review needed)"
    if src == "bot":
        a = approved.get(t)
        ref = rec if found else b
        if a is not None and (not any(a.get(k) is not None for k in _LEVEL_KEYS) or levels_match(ref, a)):
            src, status = "bot-approved", "approved by the user"
            note = note.replace("(review needed", "(approved") if note else "bot drawing (approved)"
    return {"tv_source": src, "f_bot_review": src == "bot", "tv_bot_status": status, "tv_bot_note": note}


def apply_source(r: Dict[str, Any], ticker: str, rec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fill SOURCE_COLS; a bot drawing awaiting review never counts: f_rr = False."""
    r.update(drawing_source(ticker, rec))
    if r["f_bot_review"]:
        r["f_rr"] = False
    return r


def tv_note(r: Dict[str, Any]) -> str:
    """filter_notes entry explaining a False f_rr."""
    if _truthy(r.get("f_bot_review")):
        return "TV drawing by the bot - review needed (f_rr False until approved)"
    return ({"yes": f"TV R:R {r.get('tv_rr')} < {CONFIG['rr_min']:g}", "no": "TV drawing not found"}
            .get(str(r.get("tv_found")), "no TV drawing read") + " (f_rr False)")


NEEDS_DRAWING_FILTERS = ["f_dollar_vol", "f_short_float", "f_no_earnings_14d", "f_history"]


def compute_needs_drawing(r: Dict[str, Any]) -> bool:
    """needs_drawing = f_dollar_vol AND f_short_float AND f_no_earnings_14d AND f_history
    AND no TradingView drawing (tv_found != yes; never-read tickers count until read). Informational (Grok "needs drawing" list); NOT part of status.
    Tickers with a bot drawing (tv_source bot / bot-approved, even before the nightly read
    confirms it) are excluded: they show as "review needed" instead; so are charts where the user
    drew only Fib / horizontal lines (tv_source user-lines)."""
    return bool(all(_truthy(r.get(f)) for f in NEEDS_DRAWING_FILTERS) and str(r.get("tv_found")) != "yes"
                and str(r.get("tv_source") or "") not in ("bot", "bot-approved", "user-lines"))


def finalize_status(r: Dict[str, Any]) -> Dict[str, Any]:
    failed = [f for f in CORE_FILTERS if not _truthy(r.get(f))]
    r["status"] = "PASS" if not failed else "FAIL"
    r["failed_filters"] = ",".join(f[2:] for f in failed)
    return r


def _truthy(v: Any) -> bool:
    return v is True or (not isinstance(v, str) and bool(v) and v == v) or str(v).strip().lower() in ("true", "1", "yes")


_FAIL_SUFFIX = re.compile(r"\s*\|?\s*FAIL: .*$")
_PASS_PREFIX = "PASS (all core filters) | screen: "
# screen reasons that describe the old computed geometry / R:R: never shown any more
_COMPUTED_REASON = re.compile(r"^(PASS\b|R:R\b|no weekly retest setup)")


def status_reason(r: Dict[str, Any], screen_reason: Any) -> str:
    """Idempotent reason text built from status + the TV reading.

    PASS -> "PASS (TV) entry=… SL=… TP=… R:R=… zone=[…]".
    FAIL -> "<screen reason, if it is not about the computed setup> | FAIL: <core filters>"
            with the TradingView detail when rr failed.
    """
    base = "" if screen_reason is None or (isinstance(screen_reason, float) and np.isnan(screen_reason)) else str(screen_reason)
    base = _FAIL_SUFFIX.sub("", base).strip()
    if base.startswith(_PASS_PREFIX):
        base = base[len(_PASS_PREFIX):]
    if _COMPUTED_REASON.match(base):
        base = ""
    if r["status"] == "PASS":
        return (f"PASS (TV) entry={r['tv_entry']} SL={r['tv_sl']} TP={r['tv_tp']} "
                f"R:R={r['tv_rr']} zone=[{r['tv_zone_bottom']}-{r['tv_zone_top']}]")
    fails = []
    for f in r["failed_filters"].split(","):
        if f == "rr" and _truthy(r.get("f_bot_review")):
            f = "rr (bot drawing - review needed)"
        elif f == "rr":
            rec_note = {"yes": f"TV R:R {r.get('tv_rr')} < {CONFIG['rr_min']:g}",
                        "no": "TV drawing not found"}.get(str(r.get("tv_found")), "no TV drawing read")
            f = f"rr ({rec_note})"
        fails.append(f)
    return f"{base} | FAIL: {', '.join(fails)}".strip(" |")


# ---------------------------------------------------------------------------
# report-level
# ---------------------------------------------------------------------------
def apply_filters_to_report(
    df: pd.DataFrame,
    report_date: date,
    hist_map: Optional[Dict[str, pd.DataFrame]] = None,
    universe: Optional[Dict[str, Dict[str, Any]]] = None,
    tv_store: Optional[Dict[str, Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """
    Recompute the full filter schema for every row of `df` (needs `ticker`;
    uses existing `short_float_pct` / `inst_own_pct` / `earnings_date` /
    `tradingview_url` / `finviz_url` / `reason` / `status` when present).
    Data priority — short float: row value > universe json > FinViz cache;
    earnings: row value > universe json > earnings cache. Cache-only.
    """
    _push_config_to_ssa()
    if hist_map is None:
        hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    if universe is None:
        universe = _read_json(UNIVERSE_JSON).get("tickers", {}) if UNIVERSE_JSON.exists() else {}
    if tv_store is None:
        tv_store = ss.load_tv_drawings()
    rows = []
    for _, src in df.iterrows():
        t = str(src["ticker"]).strip()
        uni = universe.get(t, {})
        fv = fv_cached(t)
        sf = _num(src.get("short_float_pct"))
        if sf is None:
            sf = _pct(uni.get("short_float"))
        if sf is None:
            sf = _pct(fv.get("short_float"))
        # Earnings: the earnings cache (absolute next date, kept until it passes)
        # is the source of truth; then universe json; then the screen row.
        ed, stale = None, None
        for cand in (earn_cached(t), uni.get("earnings_date"), src.get("earnings_date")):
            if cand is None or str(cand).strip() in ("", "nan", "None"):
                continue
            try:
                if date.fromisoformat(str(cand)[:10]) >= report_date:
                    ed = str(cand)[:10]
                    break
                stale = stale or str(cand)[:10]
            except Exception:
                continue
        ed = ed or stale  # a stale date is kept only so compute_row can note it
        tv = src.get("tradingview_url")
        r = compute_row(t, hist_map.get(t), report_date, sf, ed, _exchange_from_tv(tv),
                        tv_rec=tv_store.get(t.upper()))
        inst = _num(src.get("inst_own_pct"))
        if inst is None:
            inst = _pct(uni.get("inst_own"))
        if inst is None:
            inst = _pct(fv.get("inst_own"))
        r["inst_own_pct"] = inst
        r["tradingview_url"] = tv if isinstance(tv, str) else ""
        fz = src.get("finviz_url")
        r["finviz_url"] = fz if isinstance(fz, str) and fz else f"https://finviz.com/quote.ashx?t={t}"
        finalize_status(r)
        r["reason"] = status_reason(r, src.get("reason"))
        r["needs_drawing"] = compute_needs_drawing(r)
        rows.append(r)
    out = pd.DataFrame(rows)[REPORT_COLS]
    out["smooth_streak_weeks"] = pd.array(out["smooth_streak_weeks"], dtype="Int64")
    out["weekly_bars"] = pd.array(out["weekly_bars"], dtype="Int64")
    out["days_to_earnings"] = pd.array(out["days_to_earnings"], dtype="Int64")

    def key(i: int):
        s = 0 if out.at[i, "status"] == "PASS" else 1
        rr = _num(out.at[i, "tv_rr"])
        return (s, -(rr if rr is not None else -999.0), out.at[i, "ticker"])

    order = sorted(range(len(out)), key=key)
    return out.iloc[order].reset_index(drop=True)


def add_evidence_columns(df: pd.DataFrame, report_date: date,
                         hist_map: Optional[Dict[str, pd.DataFrame]] = None) -> pd.DataFrame:
    """Add / refresh only EVIDENCE_COLS + the zone-gated reversal columns (E1/E2) from the cached
    history (uses the row's tv_* zone)."""
    if hist_map is None:
        hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    df = df.copy()
    vals: Dict[str, List[Any]] = {c: [] for c in EVIDENCE_COLS + REVERSAL_COLS}
    for _, row in df.iterrows():
        t = str(row["ticker"]).strip()
        raw = hist_map.get(t)
        hist = None
        if raw is not None and not getattr(raw, "empty", True):
            d = ss._normalize_ohlcv_index(raw)
            d = d[d.index.normalize() <= pd.Timestamp(report_date)]
            hist = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
        r = {k: ("" if (isinstance(v, float) and np.isnan(v)) else v) for k, v in row.items()}
        e = compute_evidence(hist, r)
        if hist is not None and len(hist) >= 2:
            e.update(compute_reversals(hist, report_date, r))
        else:
            e.update({c: (False if c.startswith("f_") else "") for c in REVERSAL_COLS})
        for c in EVIDENCE_COLS + REVERSAL_COLS:
            v = e.get(c)
            vals[c].append("" if v is None else ("True" if v is True else "False" if v is False else str(v)))
    for c in EVIDENCE_COLS + REVERSAL_COLS:
        df[c] = pd.Series(vals[c], index=df.index, dtype=object)
    known = [c for c in REPORT_COLS if c in df.columns]
    return df[known + [c for c in df.columns if c not in REPORT_COLS]]


def summarize_evidence(df: pd.DataFrame) -> Dict[str, int]:
    return {c: int(df[c].map(lambda v: v is True or str(v) == "True").sum())
            for c in ("f_weekly_reversal", "f_daily_reversal", "ev_first_reaction", "ev_double_bottom",
                      "ev_ma_support", "ev_fib") if c in df.columns}


def summarize(df: pd.DataFrame) -> Dict[str, Any]:
    s = {f: int(df[f].astype(bool).sum()) for f in ALL_FILTERS}
    if "needs_drawing" in df.columns:
        s["needs_drawing"] = int(df["needs_drawing"].map(lambda v: v is True or str(v) == "True").sum())
    for f in INFO_FILTERS + ["f_tv_stale", "f_technical", "f_bot_review"]:
        if f in df.columns:
            s[f] = int(df[f].map(lambda v: v is True or str(v) == "True").sum())
    s.update(summarize_evidence(df))
    s["rows"] = int(len(df))
    s["pass"] = int((df["status"] == "PASS").sum())
    return s


def add_cli_overrides(ap: argparse.ArgumentParser) -> None:
    for k, v in CONFIG.items():
        flag = "--" + k.replace("_", "-")
        if isinstance(v, tuple):
            conv = type(v[0]) if v else str
            ap.add_argument(flag, type=lambda s, conv=conv: tuple(conv(x.strip()) for x in s.split(",") if x.strip()),
                            default=None, help=f"comma list (default {','.join(str(x) for x in v)})")
        else:
            ap.add_argument(flag, type=type(v), default=None, help=f"default {v}")


def apply_cli_overrides(args: argparse.Namespace) -> Dict[str, Any]:
    changed = {}
    for k in CONFIG:
        val = getattr(args, k, None)
        if val is not None:
            CONFIG[k] = val
            changed[k] = val
    _push_config_to_ssa()
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", type=Path, action="append", required=True,
                    help="report CSV to recompute in place (repeatable)")
    ap.add_argument("--date", required=True, help="report date YYYY-MM-DD (as-of for history/earnings)")
    ap.add_argument("--out", type=Path, default=None, help="write here instead of in place (single --report)")
    ap.add_argument("--evidence-only", action="store_true",
                    help="only add / refresh the reversal-evidence columns (ev_* + the zone-gated weekly/daily "
                         "reversal columns); every other column, "
                         "status and the Grok targets are left untouched")
    add_cli_overrides(ap)
    args = ap.parse_args()
    changed = apply_cli_overrides(args)
    if changed:
        print(f"CONFIG overrides: {changed}")
    rd = date.fromisoformat(args.date)
    hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    for p in args.report:
        if args.evidence_only:  # strings in, strings out: every existing value is kept byte-identical
            df = pd.read_csv(p, dtype=str, keep_default_na=False)
            out = add_evidence_columns(df, rd, hist_map)
            dest = args.out if args.out else p
            out.to_csv(dest, index=False)
            print(f"{dest}: evidence {summarize_evidence(out)}")
            continue
        df = pd.read_csv(p)
        out = apply_filters_to_report(df, rd, hist_map=hist_map)  # includes TV drawings (f_rr)
        dest = args.out if args.out else p
        out.to_csv(dest, index=False)
        print(f"{dest}: {summarize(out)}")


if __name__ == "__main__":
    main()
