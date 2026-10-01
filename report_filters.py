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
    # price near the TradingView support zone (TV drawings only; NOT part of status)
    "near_zone_atr_mult": 1.0,                           # f_near_zone: distance <= 1 x weekly ATR
    "near_zone_atr_period": 14,                          # weekly ATR(14), same ATR as the retest scan
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

REPORT_COLS = [
    "ticker", "status", "failed_filters",
    *CORE_FILTERS, "f_rr_computed", *EXTRA_FILTERS, *INFO_FILTERS, "needs_drawing",
    "current_price", "dollar_vol_30d", "avg_vol_30d", "short_float_pct", "inst_own_pct",
    "earnings_date", "days_to_earnings", "weekly_bars",
    "zone_lo", "zone_hi", "entry", "sl", "tp", "rr", "sl_atr_mult", "atr", "atrs_from_entry",
    *TV_COLS, *NEAR_ZONE_COLS,
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


def _scan_reversals(bars: Optional[pd.DataFrame], lookback: int) -> Tuple[bool, str, str]:
    """Shape-only reversal on any of the last `lookback` completed bars.
    Returns (hit, kind, date) of the MOST RECENT matching bar."""
    if bars is None or len(bars) < 2:
        return False, "", ""
    atr = ss.atr_series(bars, 14)
    kinds = [k for k in CONFIG["reversal_kinds"] if k in _KIND_KEY]
    n = len(bars)
    for i in range(n - 1, max(0, n - int(lookback)) - 1, -1):
        if i < 1:
            break
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
    if not r["f_rr"]:
        notes.append(tv_note(r))
    r.update(compute_near_zone(hist, r))

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
        dd = ssa.flatten_cols(daily)
        dd = ssa.completed_daily_bars(dd, as_of=as_of)
        wk = ssa.completed_weeks(ssa.to_weekly(dd), dd.index[-1])
        hit, kind, dt = _scan_reversals(wk, C["weekly_reversal_lookback_weeks"])
        r["f_weekly_reversal"], r["weekly_reversal_kind"], r["weekly_reversal_date"] = hit, kind, dt
        hit, kind, dt = _scan_reversals(dd, C["daily_reversal_lookback_days"])
        r["f_daily_reversal"], r["daily_reversal_kind"], r["daily_reversal_date"] = hit, kind, dt
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
            shot = rec.get("screenshot") or ""
            r["tv_screenshot"] = shot if shot and (_REPO_DIR / shot).exists() else ""
        else:
            r["tv_found"] = "no"
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


def tv_note(r: Dict[str, Any]) -> str:
    """filter_notes entry explaining a False f_rr."""
    return ({"yes": f"TV R:R {r.get('tv_rr')} < {CONFIG['rr_min']:g}", "no": "TV drawing not found"}
            .get(str(r.get("tv_found")), "no TV drawing read") + " (f_rr False)")


NEEDS_DRAWING_FILTERS = ["f_dollar_vol", "f_short_float", "f_no_earnings_14d", "f_history", "f_smooth_streak"]


def compute_needs_drawing(r: Dict[str, Any]) -> bool:
    """needs_drawing = TV read-target filters all true AND no TradingView drawing
    (tv_found != yes). Informational (Grok "needs drawing" list); NOT part of status."""
    return bool(all(_truthy(r.get(f)) for f in NEEDS_DRAWING_FILTERS) and str(r.get("tv_found")) != "yes")


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
        if f == "rr":
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


def summarize(df: pd.DataFrame) -> Dict[str, Any]:
    s = {f: int(df[f].astype(bool).sum()) for f in ALL_FILTERS}
    if "needs_drawing" in df.columns:
        s["needs_drawing"] = int(df["needs_drawing"].map(lambda v: v is True or str(v) == "True").sum())
    for f in INFO_FILTERS:
        if f in df.columns:
            s[f] = int(df[f].map(lambda v: v is True or str(v) == "True").sum())
    s["rows"] = int(len(df))
    s["pass"] = int((df["status"] == "PASS").sum())
    return s


def add_cli_overrides(ap: argparse.ArgumentParser) -> None:
    for k, v in CONFIG.items():
        flag = "--" + k.replace("_", "-")
        if isinstance(v, tuple):
            ap.add_argument(flag, type=lambda s: tuple(x.strip() for x in s.split(",") if x.strip()),
                            default=None, help=f"comma list (default {','.join(v)})")
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
    add_cli_overrides(ap)
    args = ap.parse_args()
    changed = apply_cli_overrides(args)
    if changed:
        print(f"CONFIG overrides: {changed}")
    rd = date.fromisoformat(args.date)
    hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    for p in args.report:
        df = pd.read_csv(p)
        out = apply_filters_to_report(df, rd, hist_map=hist_map)  # includes TV drawings (f_rr)
        dest = args.out if args.out else p
        out.to_csv(dest, index=False)
        print(f"{dest}: {summarize(out)}")


if __name__ == "__main__":
    main()
