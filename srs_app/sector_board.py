"""Sector board for the Weinstein stages page (#/stages, T-7 / Eyal 2026-11-26).

Builds a compact index (sector_board.json) plus 10-year daily OHLCV JSON for the 11 SPDR
sector ETFs, the 10 largest stocks in each sector (FinViz market cap), and any stock that
hits one of the board filters. Hooked from srs_app.stages.build so the nightly
`python -m srs_app.stages --publish` keeps it fresh.

Does not change the weekly stage machine, Buy-Stop / Sell-Stop rules, or the retest scanner.

Board badge "2a" (this UI only) = last close is above the 30-week SMA (≈ 150-day SMA) but
the price has not broken out above resistance. Distinct from the pipeline sub-stage "2A"
(a fresh weekly close above base resistance), which stays a stage-2 breakout and is shown
as badge "2".
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from srs_app.stages import (
    ETF_NAMES, RULES, SECTOR_ETF, buy_stop_price, sell_stop_price, stop_above, stop_below,
)

REPO = Path(__file__).resolve().parent.parent
OUT_BOARD = REPO / "app" / "data" / "sector_board.json"
OUT_DAILY = REPO / "app" / "data" / "sector_daily"
BOARD_CACHE = Path("/workspace/cache/sector_board_hist.pkl")
NEAR_ATRS = 1.0  # board filters only: "near" = within this many weekly ATRs of the level (not RULES.pre_bo_pct)
DAILY_YEARS = 10
TOP_N = 10
# Ordered SPDR sector ETFs (Select Sector / Real Estate).
SECTOR_ORDER = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]
SECTOR_EN = {v: k for k, v in SECTOR_ETF.items()}


def _f(x, d=2) -> Optional[float]:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), d)


def _px(x) -> Optional[float]:
    """Price rounding: 4 dp under $10, else 2 dp."""
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    v = float(x)
    return round(v, 4 if abs(v) < 10 else 2)


def resistance_of(row: Dict[str, Any]) -> Optional[float]:
    b = row.get("base") or {}
    rg = row.get("range") or {}
    idx = row.get("idx") or {}
    return _f(b.get("top") or rg.get("ceil") or idx.get("resistance"))


def support_of(row: Dict[str, Any]) -> Optional[float]:
    sb = row.get("short_base") or {}
    rg = row.get("range") or {}
    idx = row.get("idx") or {}
    return _f(sb.get("floor") or rg.get("floor") or idx.get("support"))


def broken_resistance(row: Dict[str, Any]) -> Optional[float]:
    """Former base ceiling that stage-2 broke (now support). Prefer a recorded or derived breakout level."""
    bo = row.get("bo") or {}
    if bo.get("level"):
        return _f(bo["level"])
    if row.get("_bo_lvl"):
        return _f(row["_bo_lvl"])
    rg = row.get("range") or {}
    return _f(rg.get("floor"))


def broken_support(row: Dict[str, Any]) -> Optional[float]:
    """Former base floor that stage-4 broke (now resistance from below). Prefer a recorded breakdown level."""
    bd = row.get("bd") or {}
    if bd.get("level"):
        return _f(bd["level"])
    return None


def above_ma(close: Optional[float], ma30: Optional[float]) -> bool:
    return close is not None and ma30 is not None and close > ma30


def board_badge(row: Dict[str, Any]) -> str:
    """UI badge: 1, 2a, 2, 3 or 4.

    2a = stage 1 (not yet a breakout) AND close > 30W / 150d SMA. Pipeline sub '2A'
    (fresh stage-2 breakout) remains badge '2'.
    """
    try:
        stage = int(row.get("stage") or 0)
    except (TypeError, ValueError):
        stage = 0
    if stage == 1 and above_ma(row.get("close"), row.get("ma30")):
        return "2a"
    return str(stage) if stage in (1, 2, 3, 4) else "?"


def near_level(close: Optional[float], level: Optional[float], from_below: bool,
               atr_w: Optional[float] = None, near_atrs: float = NEAR_ATRS) -> bool:
    """True when close is on the correct side of `level` (or on it) and within near_atrs weekly ATRs."""
    if close is None or not level or atr_w is None or atr_w <= 0:
        return False
    dist = (level - close) if from_below else (close - level)
    return 0 <= dist <= near_atrs * atr_w


def near_abs(close: Optional[float], level: Optional[float],
             atr_w: Optional[float] = None, near_atrs: float = NEAR_ATRS) -> bool:
    """True when |close - level| is within near_atrs weekly ATRs."""
    if close is None or not level or atr_w is None or atr_w <= 0:
        return False
    return abs(close - level) <= near_atrs * atr_w


def flag_near_res(row: Dict[str, Any], badge: Optional[str] = None, near_atrs: float = NEAR_ATRS) -> bool:
    """Main long filter: badge 2a and close within 1 weekly ATR under resistance."""
    b = badge or board_badge(row)
    return b == "2a" and near_level(row.get("close"), resistance_of(row), from_below=True,
                                    atr_w=row.get("atr_w"), near_atrs=near_atrs)


def flag_near_sup(row: Dict[str, Any], near_atrs: float = NEAR_ATRS) -> bool:
    """Main short-side filter: stage 3 and close within 1 weekly ATR above support."""
    try:
        stage = int(row.get("stage") or 0)
    except (TypeError, ValueError):
        return False
    return stage == 3 and near_level(row.get("close"), support_of(row), from_below=False, atr_w=row.get("atr_w"), near_atrs=near_atrs)


def last_breakout_level(w, lookback_w: int = 52) -> Optional[float]:
    """Most recent valid base breakout in the last lookback_w weeks (same tests as find_breakout,
    but scanning newest-first and looking further back than the 3-week entry window)."""
    import numpy as np
    from srs_app.stages import _base_count, slope_class
    if w is None or len(w) < RULES["base_window_w"] + RULES["min_base_w"]:
        return None
    h, c = w["High"].values, w["Close"].values
    ma = w["Close"].rolling(int(RULES["ma_weeks"])).mean().values
    n = len(w)
    start = max(int(RULES["base_window_w"]), n - 1 - lookback_w)
    for b in range(n - 1, start - 1, -1):
        seg = h[b - int(RULES["base_window_w"]):b]
        if len(seg) == 0:
            continue
        res = float(seg.max())
        top_i = b - int(RULES["base_window_w"]) + int(np.argmax(seg))
        if not (c[b] > res and c[b] > ma[b]):
            continue
        sc, _ = slope_class(ma, b, RULES)
        if sc not in ("up", "flat"):
            continue
        base = _base_count(c, b - 1, res)
        if base < RULES["min_base_w"] or (b - top_i) < RULES["min_base_w"]:
            continue
        return _f(res)
    return None


def flag_retest2(row: Dict[str, Any], near_atrs: float = NEAR_ATRS) -> bool:
    """Stage 2 pulling back to the broken resistance (now support) — long retest.

    Needs a breakout level: recorded bo.level, or one derived from weekly history
    (row['_bo_lvl'], set in write_board). Range floor alone is not enough.
    """
    try:
        stage = int(row.get("stage") or 0)
    except (TypeError, ValueError):
        return False
    if stage != 2:
        return False
    lvl = (row.get("bo") or {}).get("level") or row.get("_bo_lvl")
    return near_abs(row.get("close"), _f(lvl), atr_w=row.get("atr_w"), near_atrs=near_atrs)


def flag_retest4(row: Dict[str, Any], near_atrs: float = NEAR_ATRS) -> bool:
    """Stage 4 rallying back to the broken support (now resistance) — short retest.

    Requires a recorded breakdown level (bd.level) so a stock sitting on new lows is not
    mistaken for a retest of the broken floor.
    """
    try:
        stage = int(row.get("stage") or 0)
    except (TypeError, ValueError):
        return False
    if stage != 4:
        return False
    return near_abs(row.get("close"), broken_support(row), atr_w=row.get("atr_w"), near_atrs=near_atrs)


def _long_levels(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """(resistance or broken-res, buy-stop entry, Stef/Weinstein stop). Reuses existing plan when present."""
    res = resistance_of(row)
    plan = row.get("plan") or {}
    entry = _f(plan.get("entry")) or (_f(buy_stop_price(res, RULES)) if res else None)
    stop = _f(plan.get("stop"))
    if stop is None:
        low = (row.get("base") or {}).get("low") or support_of(row)
        ma = row.get("ma30")
        anchors = [x for x in (ma, low) if x]
        if anchors:
            stop = _f(stop_below(min(anchors), RULES))
    return res, entry, stop


def _short_levels(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    sup = support_of(row)
    plan = row.get("short_plan") or {}
    entry = _f(plan.get("entry")) or (_f(sell_stop_price(sup, RULES)) if sup else None)
    stop = _f(plan.get("stop"))
    if stop is None:
        high = (row.get("short_base") or {}).get("top") or resistance_of(row)
        ma = row.get("ma30")
        anchors = [x for x in (ma, high) if x]
        if anchors:
            stop = _f(stop_above(max(anchors), RULES))
    return sup, entry, stop


def recommend(row: Dict[str, Any], badge: Optional[str] = None, flags: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """Hebrew recommendation only — never an order. Filled from the chart / existing plan and Stef stop."""
    badge = badge or board_badge(row)
    flags = flags or {}
    close = row.get("close")
    ma = _f(row.get("ma30"))
    res, long_entry, long_sl = _long_levels(row)
    sup, short_entry, short_sl = _short_levels(row)
    bo_lvl = broken_resistance(row) if int(row.get("stage") or 0) == 2 else None
    bd_lvl = broken_support(row)
    disclaimer = " המלצה בלבד — המערכת לא מציבה פקודות."

    def px(v: Optional[float]) -> str:
        return f"${v:.2f}" if v is not None else "—"

    kind, he = "wait", "אין המלצה ברורה מהגרף — להמתין."
    entry, stop, side = None, None, None

    if badge == "2a":
        if flags.get("near_res") and res and long_entry:
            kind, side, entry, stop = "buy_stop", "long", long_entry, long_sl
            he = (f"המלצה: פקודת Buy-Stop מעל ההתנגדות ב-{px(long_entry)} "
                  f"(תקרה {px(res)}), סטופ לפי כלל ויינשטיין/Stef ב-{px(long_sl)}.")
        elif res:
            kind, side, entry, stop = "wait_breakout", "long", long_entry, long_sl
            he = (f"מעל ממוצע 150 יום, לפני הפריצה — להמתין לסגירה מעל ההתנגדות {px(res)}."
                  + (f" אחרי הפריצה אפשר לשקול Buy-Stop ב-{px(long_entry)}, SL ב-{px(long_sl)}." if long_entry else ""))
        else:
            kind = "wait_breakout"
            he = "מעל ממוצע 150 יום, לפני הפריצה — להמתין להתבהרות רמת ההתנגדות."
    elif int(row.get("stage") or 0) == 1:
        kind = "wait_sma"
        he = "להמתין לסגירה מעל ממוצע 150 יום (30 שבועות)" + (f" ({px(ma)})." if ma else ".")
    elif flags.get("retest2") and bo_lvl:
        kind, side, entry, stop = "limit_retest", "long", bo_lvl, long_sl
        he = (f"המלצה: פקודת לימיט בריטסט של ההתנגדות שנפרצה ({px(bo_lvl)}), "
              f"סטופ לפי כלל ויינשטיין/Stef ב-{px(long_sl)}.")
    elif int(row.get("stage") or 0) == 2:
        ext = bool(ma and close and close > ma * (1 + float(RULES.get("max_pct_above_ma", 25)) / 100))
        if ext:
            kind, side = "wait_retest", "long"
            he = "שלב 2 מתוחה מעל הממוצע — לא לרדוף. להמתין לריטסט של רמת הפריצה או של ממוצע 150 יום."
        else:
            kind, side, entry, stop = "wait_retest", "long", long_entry, long_sl
            he = "שלב 2 — להמתין לריטסט של ההתנגדות שנפרצה" + (f" ({px(bo_lvl)})." if bo_lvl else ".")
            if long_entry:
                he += f" אם מופיע טריגר: Buy-Stop ב-{px(long_entry)}, SL ב-{px(long_sl)}."
    elif int(row.get("stage") or 0) == 3:
        if flags.get("near_sup") and sup and short_entry:
            kind, side, entry, stop = "sell_stop", "short", short_entry, short_sl
            he = (f"המלצה: פקודת Sell-Stop מתחת לתמיכה ב-{px(short_entry)} "
                  f"(רצפה {px(sup)}), סטופ ב-{px(short_sl)}. לחילופין להמתין ליציאה כלפי מעלה מעל הממוצע.")
        elif sup:
            kind, side = "wait_support", "short"
            he = f"שלב 3 — להמתין להתקרבות לתמיכה {px(sup)} (אז Sell-Stop) או לפריצה חזרה מעל הממוצע."
        else:
            kind = "wait"
            he = "שלב 3 (פסגה) — להמתין לשבירת התמיכה או לחזרה מעל הממוצע."
    elif flags.get("retest4") and bd_lvl:
        kind, side, entry, stop = "limit_retest_short", "short", bd_lvl, short_sl
        he = (f"המלצה (שורט): לימיט / Sell-Stop בריטסט של התמיכה שנשברה ({px(bd_lvl)}), "
              f"סטופ ב-{px(short_sl)}.")
    elif int(row.get("stage") or 0) == 4:
        kind, side = "wait_retest_short", "short"
        he = "שלב 4 — להמתין לריטסט מלמטה של התמיכה שנשברה, או להישאר בחוץ אם המניה מתוחה מטה."

    return {"kind": kind, "he": he + disclaimer, "entry": entry, "stop": stop, "side": side,
            "res": res, "sup": sup, "bo_lvl": bo_lvl, "bd_lvl": bd_lvl}


def flags_of(row: Dict[str, Any], badge: Optional[str] = None, near_atrs: float = NEAR_ATRS) -> Dict[str, bool]:
    b = badge or board_badge(row)
    return {
        "near_res": flag_near_res(row, b, near_atrs),
        "near_sup": flag_near_sup(row, near_atrs),
        "retest2": flag_retest2(row, near_atrs),
        "retest4": flag_retest4(row, near_atrs),
    }


def stock_card(row: Dict[str, Any], near_atrs: float = NEAR_ATRS, hist_start: Optional[str] = None,
               hist_days: Optional[int] = None) -> Dict[str, Any]:
    badge = board_badge(row)
    flags = flags_of(row, badge, near_atrs)
    rec = recommend(row, badge, flags)
    return {
        "t": row["t"], "n": row.get("n"), "sec": row.get("sec"), "etf": row.get("sec_etf") or row.get("etf"),
        "mcap_b": row.get("mcap_b"), "stage": row.get("stage"), "sub": row.get("sub"), "badge": badge,
        "close": _f(row.get("close")), "ma30": _f(row.get("ma30")), "atr_w": _f(row.get("atr_w")),
        "res": rec["res"], "sup": rec["sup"], "bo_lvl": rec["bo_lvl"], "bd_lvl": rec["bd_lvl"],
        "flags": flags, "rec": rec, "hist_start": hist_start, "hist_days": hist_days,
    }


def etf_row(etf: str, e: Dict[str, Any]) -> Dict[str, Any]:
    """A stages-like row for a SPDR sector ETF, so stock_card / recommend can run unchanged."""
    return {
        "t": etf, "n": ETF_NAMES.get(etf, etf), "sec": SECTOR_EN.get(etf, etf),
        "sec_etf": etf, "etf": etf, "mcap_b": None,
        "stage": e.get("stage"), "sub": e.get("sub"), "close": e.get("close"),
        "ma30": e.get("ma30"), "atr_w": e.get("atr_w"),
        "range": e.get("range"), "base": e.get("base"), "idx": e.get("idx"),
        "bo": e.get("bo"), "bd": e.get("bd"), "plan": e.get("plan"),
        "short_plan": e.get("short_plan"), "short_base": e.get("short_base"),
    }


def etf_as_stock(etf: str, e: Dict[str, Any], near_atrs: float = NEAR_ATRS,
                 hist_start: Optional[str] = None, hist_days: Optional[int] = None) -> Dict[str, Any]:
    """Board card for the sector ETF itself (first mini when that sector is open)."""
    card = stock_card(etf_row(etf, e), near_atrs, hist_start, hist_days)
    card["is_sector"] = True
    card["n"] = ETF_NAMES.get(etf, etf)
    card["etf"] = etf
    return card


def sector_card(etf: str, e: Dict[str, Any], tickers: List[str]) -> Dict[str, Any]:
    row = {
        "t": etf, "stage": e.get("stage"), "sub": e.get("sub"), "close": e.get("close"),
        "ma30": e.get("ma30"), "range": e.get("range"), "base": e.get("base"), "idx": e.get("idx"),
        "bo": e.get("bo"), "bd": e.get("bd"), "plan": e.get("plan"), "short_plan": e.get("short_plan"),
        "short_base": e.get("short_base"),
    }
    badge = board_badge(row)
    return {
        "etf": etf, "name": ETF_NAMES.get(etf, etf), "name_en": SECTOR_EN.get(etf, etf),
        "stage": e.get("stage"), "sub": e.get("sub"), "badge": badge,
        "close": _f(e.get("close")), "ma30": _f(e.get("ma30")), "atr_w": _f(e.get("atr_w")),
        "res": resistance_of(row), "sup": support_of(row), "rs": e.get("rs"),
        "stocks": tickers,
    }


def top_stocks(rows: List[Dict[str, Any]], etf: str, n: int = TOP_N) -> List[Dict[str, Any]]:
    pool = [r for r in rows if (r.get("sec_etf") or SECTOR_ETF.get(r.get("sec") or "")) == etf]
    pool.sort(key=lambda r: -(r.get("mcap_b") or 0))
    return pool[:n]


def filter_lists(rows: List[Dict[str, Any]], near_atrs: float = NEAR_ATRS) -> Dict[str, List[str]]:
    out = {"2a_res": [], "3_sup": [], "retest2": [], "retest4": []}
    for r in rows:
        b = board_badge(r)
        if flag_near_res(r, b, near_atrs):
            out["2a_res"].append(r["t"])
        if flag_near_sup(r, near_atrs):
            out["3_sup"].append(r["t"])
        if flag_retest2(r, near_atrs):
            out["retest2"].append(r["t"])
        if flag_retest4(r, near_atrs):
            out["retest4"].append(r["t"])
    return out


def _daily_payload(t: str, d: pd.DataFrame, years: int = DAILY_YEARS) -> str:
    df = d.copy()
    df.index = pd.to_datetime(df.index)
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    cutoff = pd.Timestamp(df.index.max()).normalize() - pd.DateOffset(years=years)
    df = df[df.index >= cutoff]
    rows = []
    for ix, row in df[["Open", "High", "Low", "Close", "Volume"]].iterrows():
        o, h, l, c = (_px(row[k]) for k in ("Open", "High", "Low", "Close"))
        if None in (o, h, l, c):
            continue
        vol = int(row["Volume"]) if pd.notna(row["Volume"]) else 0
        rows.append([ix.strftime("%Y-%m-%d"), o, h, l, c, vol])
    return json.dumps({"t": t, "d": rows}, separators=(",", ":"))


def write_daily(t: str, d: pd.DataFrame, years: int = DAILY_YEARS) -> Path:
    OUT_DAILY.mkdir(parents=True, exist_ok=True)
    payload = _daily_payload(t, d, years)
    cp = OUT_DAILY / f"{t}.json"
    if not cp.exists() or cp.read_text() != payload:
        cp.write_text(payload)
    return cp


def prune_daily(keep: Iterable[str]) -> int:
    """Remove daily files that are no longer in the board set."""
    if not OUT_DAILY.exists():
        return 0
    keep_set = set(keep)
    n = 0
    for p in OUT_DAILY.glob("*.json"):
        if p.stem not in keep_set:
            p.unlink()
            n += 1
    return n


def _hist_meta(df: Optional[pd.DataFrame]) -> Tuple[Optional[str], Optional[int]]:
    if df is None or getattr(df, "empty", True):
        return None, None
    idx = pd.to_datetime(df.index)
    return str(pd.Timestamp(idx.min()).date()), int(len(df))


def _last_daily(df: Optional[pd.DataFrame]) -> Tuple[Optional[float], Optional[str]]:
    """Last daily close and its session date (the chart's last candle). Weekly close stays on the card as 'close'."""
    if df is None or getattr(df, "empty", True):
        return None, None
    try:
        asof = pd.Timestamp(pd.to_datetime(df.index).max()).strftime("%Y-%m-%d")
        return _f(df["Close"].iloc[-1]), asof
    except Exception:
        return None, None


def ensure_board_history(tickers: List[str], hm: Dict[str, pd.DataFrame], offline: bool = False) -> Dict[str, pd.DataFrame]:
    """10-year daily history for board tickers only (separate cache; does not rewrite the 5y stage cache)."""
    out: Dict[str, pd.DataFrame] = {}
    if BOARD_CACHE.exists():
        try:
            cached = pd.read_pickle(BOARD_CACHE)
            if isinstance(cached, dict):
                out.update(cached)
        except Exception as e:
            print(f"[sector_board] could not read {BOARD_CACHE}: {e}")
    for t in tickers:
        a, b = out.get(t), hm.get(t)
        if a is None or getattr(a, "empty", True):
            if b is not None and not getattr(b, "empty", True):
                out[t] = b
            continue
        if b is None or getattr(b, "empty", True):
            continue
        # union: prefer the longer / more recent series, merge on date
        try:
            aa = a.copy(); aa.index = pd.to_datetime(aa.index)
            bb = b.copy(); bb.index = pd.to_datetime(bb.index)
            if getattr(aa.index, "tz", None) is not None:
                aa.index = aa.index.tz_localize(None)
            if getattr(bb.index, "tz", None) is not None:
                bb.index = bb.index.tz_localize(None)
            merged = bb.combine_first(aa) if len(bb) >= len(aa) else aa.combine_first(bb)
            # last-wins for overlapping dates from the fresher map (hm)
            overlap = aa.index.intersection(bb.index)
            if len(overlap):
                merged.loc[overlap] = bb.loc[overlap]
            out[t] = merged.sort_index()
        except Exception:
            out[t] = b if (b is not None and len(b) >= len(a)) else a

    if offline:
        return {t: out[t] for t in tickers if t in out}

    need: List[str] = []
    today = date.today()
    cutoff = pd.Timestamp(today) - pd.DateOffset(years=DAILY_YEARS, days=30)
    for t in tickers:
        df = out.get(t)
        if df is None or getattr(df, "empty", True):
            need.append(t)
            continue
        start = pd.Timestamp(pd.to_datetime(df.index).min())
        if start.tzinfo is not None:
            start = start.tz_localize(None)
        if start > cutoff:
            need.append(t)
    if need:
        try:
            import stock_screen as ss
            start = (pd.Timestamp(today) - pd.DateOffset(years=DAILY_YEARS)).strftime("%Y-%m-%d")
            print(f"[sector_board] fetching ~{DAILY_YEARS}y daily for {len(need)} tickers from {start}")
            extra = ss.download_batch(need, chunk=50, start=start)
            target = getattr(ss, "last_us_session_date", lambda: pd.Timestamp(today))()
            for t, new_df in extra.items():
                if new_df is None or getattr(new_df, "empty", True):
                    continue
                new_df = ss._normalize_ohlcv_index(new_df)
                new_df = new_df[new_df.index.normalize() <= target]
                old = out.get(t)
                if old is not None and not getattr(old, "empty", True):
                    merged = ss.merge_refresh(old, new_df, target)
                    if merged is not None and not getattr(merged, "empty", True):
                        out[t] = merged
                    else:
                        out[t] = new_df
                else:
                    out[t] = new_df
        except Exception as e:
            print(f"[sector_board] 10y fetch failed (will use cached history): {e}")

    BOARD_CACHE.parent.mkdir(parents=True, exist_ok=True)
    keep = {t: out[t] for t in set(tickers) | set(out) if t in out and out[t] is not None}
    # don't let the cache grow without bound: keep current board + a small cushion already in out
    try:
        pd.to_pickle({t: keep[t] for t in tickers if t in keep}, BOARD_CACHE)
    except Exception as e:
        print(f"[sector_board] could not write {BOARD_CACHE}: {e}")
    return {t: out[t] for t in tickers if t in out}


def write_board(doc: Dict[str, Any], hm: Optional[Dict[str, pd.DataFrame]] = None,
                offline: bool = False, near_atrs: float = NEAR_ATRS) -> Dict[str, Any]:
    """Write sector_board.json + compact daily JSON. Returns the board document."""
    raw_rows: List[Dict[str, Any]] = list(doc.get("rows") or [])
    sectors_doc: Dict[str, Any] = doc.get("sectors") or {}
    rows = list(raw_rows)
    if hm:
        from srs_app.stages import weekly as _weekly
        last = None
        for ttry in ("SPY", "QQQ"):
            df = hm.get(ttry)
            if df is not None and len(df):
                last = pd.Timestamp(pd.to_datetime(df.index).max()).normalize()
                break
        if last is None:
            for df in hm.values():
                if df is not None and len(df):
                    last = pd.Timestamp(pd.to_datetime(df.index).max()).normalize()
                    break
        derived: List[Dict[str, Any]] = []
        for r in rows:
            if int(r.get("stage") or 0) == 2 and not (r.get("bo") or {}).get("level"):
                df = hm.get(r["t"])
                if df is not None and not getattr(df, "empty", True) and last is not None:
                    try:
                        lvl = last_breakout_level(_weekly(df, last))
                    except Exception:
                        lvl = None
                    if lvl:
                        r = dict(r)
                        r["_bo_lvl"] = lvl
            derived.append(r)
        rows = derived
    flists = filter_lists(rows, near_atrs)
    want: set[str] = set(SECTOR_ORDER)
    sector_blocks: List[Dict[str, Any]] = []
    for etf in SECTOR_ORDER:
        e = sectors_doc.get(etf) or {}
        tops = top_stocks(rows, etf, TOP_N)
        sector_blocks.append(sector_card(etf, e, [r["t"] for r in tops]))
        want.update(r["t"] for r in tops)
    for ts in flists.values():
        want.update(ts)

    hist = ensure_board_history(sorted(want), hm or {}, offline=offline)
    stocks: Dict[str, Any] = {}
    by_t = {r["t"]: r for r in rows}
    for tkr in sorted(want):
        start, ndays = _hist_meta(hist.get(tkr))
        if tkr in SECTOR_ORDER:
            e = sectors_doc.get(tkr) or {}
            if not e:
                continue
            r = etf_row(tkr, e)
            if int(r.get("stage") or 0) == 2 and not (r.get("bo") or {}).get("level"):
                df = hist.get(tkr)
                if df is not None and not getattr(df, "empty", True):
                    try:
                        from srs_app.stages import weekly as _weekly
                        last = pd.Timestamp(pd.to_datetime(df.index).max()).normalize()
                        lvl = last_breakout_level(_weekly(df, last))
                    except Exception:
                        lvl = None
                    if lvl:
                        r["_bo_lvl"] = lvl
            card = stock_card(r, near_atrs, start, ndays)
            card["is_sector"] = True
            card["n"] = ETF_NAMES.get(tkr, tkr)
            card["etf"] = tkr
            cd, asof = _last_daily(hist.get(tkr))
            if cd is not None:
                card["close_d"] = cd
                card["asof_d"] = asof
            stocks[tkr] = card
            continue
        r = by_t.get(tkr)
        if not r:
            continue
        card = stock_card(r, near_atrs, start, ndays)
        cd, asof = _last_daily(hist.get(tkr))
        if cd is not None:
            card["close_d"] = cd
            card["asof_d"] = asof
        stocks[tkr] = card

    written = 0
    years_ok = 0
    for t in sorted(want):
        df = hist.get(t)
        if df is None or getattr(df, "empty", True):
            continue
        write_daily(t, df)
        written += 1
        start, _ = _hist_meta(df)
        if start and start <= (date.today().replace(year=date.today().year - (DAILY_YEARS - 1))).isoformat():
            years_ok += 1
    gone = prune_daily(want)

    # history coverage for the report
    starts = [stocks[t]["hist_start"] for t in stocks if stocks[t].get("hist_start")]
    board = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "week": doc.get("week"),
        "source": "SPDR Select Sector ETFs (XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLB, XLRE, XLC) — FinViz sector map in srs_app.stages.SECTOR_ETF",
        "badge_2a": "close above the 30-week SMA (≈150-day) and still at or below base resistance (pre-breakout). Distinct from pipeline sub-stage 2A (fresh stage-2 breakout), which is shown as badge 2.",
        "near_atrs": near_atrs,
        "near": "1 weekly ATR (board filters only; RULES.pre_bo_pct for Buy-Stop is unchanged)",
        "daily_years": DAILY_YEARS,
        "daily_path": "sector_daily/{t}.json",
        "top_n": TOP_N,
        "sectors": sector_blocks,
        "stocks": stocks,
        "filters": flists,
        "daily_written": written,
        "daily_pruned": gone,
        "hist_min_start": min(starts) if starts else None,
        "hist_max_start": max(starts) if starts else None,
        "hist_full_years": years_ok,
    }
    OUT_BOARD.parent.mkdir(parents=True, exist_ok=True)
    OUT_BOARD.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")))
    print(f"[sector_board] {len(sector_blocks)} sectors, {len(stocks)} stocks, {written} daily files "
          f"(pruned {gone}) filters { {k: len(v) for k, v in flists.items()} } -> {OUT_BOARD} "
          f"({OUT_BOARD.stat().st_size // 1024} KB)")
    return board
