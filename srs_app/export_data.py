"""Export static data for the web app (published to GitHub Pages under /app/data/).

Writes, relative to the repo root:
  app/data/index.json          candidate list (badges + key levels) from historical-reports/latest.csv
  app/data/tv_drawings.json    read-only TradingView drawings (source 'tv') from /workspace/stock-screener/tv_drawings.json
  app/data/candles/<T>.json    daily OHLCV, 5 years, from the scanner's history cache (/workspace/hist_cache.pkl)
  app/data/spark.json          list mini charts: last SPARK_WEEKS weekly (W-FRI) OHLC candles per exported ticker, 1 byte/value

Candidates = PASS ∪ needs_drawing ∪ bot review ∪ obsolete (tv_stale) ∪ last-week hammer (gated, see hammer_ok)
             ∪ any TradingView drawing found ∪ open positions.

Hammer gate (Eyal 2026-10-23): a last-week hammer only earns the 'hammer' badge / list inclusion when it also passes the
basic must-haves f_dollar_vol AND f_history AND f_no_earnings_14d (report columns; unknown earnings = not passing).

Usage:  python -m srs_app.export_data [--repo .] [--all]
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from srs_app.fib import fib_anchor

HIST_CACHE = Path(os.environ.get("SRS_HIST_CACHE", "/workspace/hist_cache.pkl"))
TV_DRAWINGS = Path(os.environ.get("SRS_TV_DRAWINGS", "/workspace/stock-screener/tv_drawings.json"))
# Sector / industry per ticker (list card, Eyal 2026-10-24). FinViz quote page first, yfinance fallback; cached because
# a company's sector rarely changes: hits kept SECTOR_TTL_DAYS, misses retried after SECTOR_MISS_TTL_DAYS.
SECTOR_CACHE = Path(os.environ.get("SRS_SECTOR_CACHE", "/workspace/cache/sector_industry.json"))
SECTOR_TTL_DAYS = 120
SECTOR_MISS_TTL_DAYS = 7
YEARS = 5
SPARK_WEEKS = 156  # ~3 years of weekly closes for the list mini chart
SPARK_Q = 255      # OHLC quantized to one byte between lo and hi (keeps spark.json small)

INDEX_COLS = [
    "ticker", "status", "current_price", "dollar_vol_30d", "days_to_earnings", "earnings_date", "earnings_none", "earnings_estimated",
    "tv_zone_top", "tv_zone_bottom", "tv_entry", "tv_sl", "tv_tp", "tv_rr", "tv_source", "tv_read_date",
    "tv_zone_dist_atr", "tv_stale", "tv_stale_detail", "tv_bot_status", "weekly_atr",
    "f_technical", "f_near_zone", "needs_drawing", "f_bot_review", "f_tv_stale", "f_last_week_reversal",
    "last_week_reversal_kind", "hammer_entry", "hammer_sl", "hammer_tp", "hammer_rr", "hammer_calm_weeks",
    "hammer_score", "inst_own_pct", "short_float_pct", "tradingview_url",
    "f_dollar_vol", "f_history", "f_no_earnings_14d",
    "f_no_red_vol_week", "red_vol_week_date", "red_vol_body_pct", "red_vol_ratio", "red_vol_detail",
    "f_from_above", "from_above_side", "from_above_date", "from_above_detail",
    "f_no_inv_hammer", "inv_hammer_week_date", "inv_hammer_detail",
    # independent list filters (Eyal 2026-10-26)
    "smooth_streak_weeks", "f_smooth_streak",
]
# 'reversal candle within X weeks' filters: the most recent reversal-shape candle (no zone gate) of the last
# REV_LOOKBACK_WEEKS weeks, daily and weekly (report_filters.last_reversal)
REV_LOOKBACK_WEEKS = 26


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if hasattr(v, "item"):
        return _clean(v.item())
    if isinstance(v, str):
        s = v.strip()
        if s in ("True", "true"):
            return True
        if s in ("False", "false"):
            return False
        return s or None
    return v


def _truthy(v: Any) -> bool:
    return _clean(v) is True or str(v).strip().lower() in ("yes", "true", "1")


HAMMER_MUST_HAVES = ("f_dollar_vol", "f_history", "f_no_earnings_14d")


def hammer_ok(r: Any) -> bool:
    """Last-week hammer that also passes the must-haves ($vol, 3y history, no earnings within 14d; unknown = fail)."""
    return _truthy(r.get("f_last_week_reversal")) and all(_truthy(r.get(c)) for c in HAMMER_MUST_HAVES)


def build_index(repo: Path, include_all: bool = False, report: Path | None = None) -> List[Dict[str, Any]]:
    df = pd.read_csv(report or (repo / "historical-reports" / "latest.csv"))
    positions = set()
    pj = repo / "positions.json"
    if pj.exists():
        for p in json.loads(pj.read_text()).get("positions", []):
            if p.get("status") == "open":
                positions.add(p["ticker"])
    rows = []
    for _, r in df.iterrows():
        badges = []
        if r.get("status") == "PASS":
            badges.append("pass")
        # (WAIT / badge 'waiting' cancelled 2026-10-26: the app shows the red-volume / inverted-hammer warnings
        # from f_no_red_vol_week / f_no_inv_hammer as info badges)
        if _truthy(r.get("needs_drawing")):
            badges.append("needs_drawing")
        if _truthy(r.get("f_bot_review")):
            badges.append("review")
        if _truthy(r.get("f_tv_stale")):
            badges.append("obsolete")
        if hammer_ok(r):
            badges.append("hammer")
        if r["ticker"] in positions:
            badges.append("position")
        has_tv = str(r.get("tv_found")).lower() in ("yes", "true")
        if not (badges or has_tv or include_all):
            continue
        row = {c: _clean(r.get(c)) for c in INDEX_COLS if c in df.columns}
        row["badges"] = badges
        row["tv_found"] = has_tv
        rows.append(row)
    return rows


def fetch_sector(ticker: str) -> Dict[str, Any]:
    """{'sector', 'industry', 'src'} from FinViz (quote page header), else yfinance .info; None = unknown."""
    out: Dict[str, Any] = {"sector": None, "industry": None, "src": None}
    try:
        from srs.info import finviz_snapshot
        s = finviz_snapshot(ticker)
        out.update(sector=s.get("_sector"), industry=s.get("_industry"))
        out["src"] = "finviz" if (out["sector"] or out["industry"]) else None
    except Exception as e:
        print(f"  [sector] finviz {ticker}: {e}")
    if not out["sector"] or not out["industry"]:
        try:
            import yfinance as yf
            inf = yf.Ticker(ticker.replace(".", "-")).info or {}
            if inf.get("sector") or inf.get("industry"):
                out["sector"] = out["sector"] or inf.get("sector")
                out["industry"] = out["industry"] or inf.get("industry")
                out["src"] = "finviz+yfinance" if out["src"] else "yfinance"
        except Exception as e:
            print(f"  [sector] yfinance {ticker}: {e}")
    return out


def attach_sectors(rows: List[Dict[str, Any]], cache_path: Optional[Path] = None, fetch=None,
                   now: Optional[datetime] = None, max_fetch: int = 400) -> int:
    """Set row['sector'] / row['industry'] (None = unknown, shown as '—') from the cache, fetching missing/expired
    tickers (at most max_fetch per run). SRS_NO_NET=1 disables fetching. Returns the number of fetches."""
    import time
    cache_path = cache_path or SECTOR_CACHE
    fetch = fetch or (None if os.environ.get("SRS_NO_NET") else fetch_sector)
    now = now or datetime.now(timezone.utc)
    try:
        cache: Dict[str, Any] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except Exception:
        cache = {}

    def fresh(e: Dict[str, Any]) -> bool:
        try:
            age = (now - datetime.fromisoformat(e["fetched"])).days
        except Exception:
            return False
        return age < (SECTOR_TTL_DAYS if e.get("sector") else SECTOR_MISS_TTL_DAYS)

    n = 0
    for r in rows:
        t = r["ticker"]
        e = cache.get(t)
        if fetch and (e is None or not fresh(e)) and n < max_fetch:
            got = fetch(t) or {}
            n += 1
            if got.get("sector") or got.get("industry") or e is None or not e.get("sector"):
                e = {"sector": got.get("sector"), "industry": got.get("industry"), "src": got.get("src"),
                     "fetched": now.isoformat(timespec="seconds")}
                cache[t] = e
            if fetch is fetch_sector:
                time.sleep(0.35)
        r["sector"] = (e or {}).get("sector") or None
        r["industry"] = (e or {}).get("industry") or None
    if n:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=0, sort_keys=True))
        except Exception as ex:
            print(f"  [sector] cache write failed: {ex}")
    return n


def load_watchlist() -> List[str]:
    """Watchlist tickers from the app (bot writes /workspace/stock-screener/app_state.json via srs_app.sync.write_app_state)."""
    try:
        from srs_app.sync import watchlist_from_state
        return [t for t in watchlist_from_state(os.environ.get("SRS_APP_STATE", "/workspace/stock-screener/app_state.json")) if t]
    except Exception as e:
        print(f"  [app data] watchlist skipped: {e}")
        return []


def export_tv(out: Path) -> Dict[str, Any]:
    src = json.loads(TV_DRAWINGS.read_text()) if TV_DRAWINGS.exists() else {}
    keep = {}
    for t, d in src.items():
        if not d.get("found") and d.get("zone_top") is None and d.get("entry") is None:
            continue
        keep[t] = {
            "ticker": t, "source": "tv", "owner": d.get("source") or None,
            "zone_top": d.get("zone_top"), "zone_bottom": d.get("zone_bottom"),
            "entry": d.get("entry"), "stop": d.get("sl"), "target": d.get("tp"), "rr": d.get("rr"),
            "read_date": d.get("read_date"), "symbol": d.get("symbol"),
        }
    (out / "tv_drawings.json").write_text(json.dumps(keep, separators=(",", ":")))
    return keep


def _download_missing(tickers: List[str]) -> Dict[str, pd.DataFrame]:
    """Tickers not in the scanner cache (e.g. watchlist adds): 5y daily from yfinance, same settings as the screen."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
        data = yf.download(tickers=tickers, period=f"{YEARS}y", interval="1d", group_by="ticker",
                           auto_adjust=True, threads=True, progress=False)
    except Exception as e:
        print(f"  [app data] download failed for {tickers}: {e}")
        return {}
    out = {}
    for t in tickers:
        try:
            df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            df = df.dropna(how="all")
            if not df.empty:
                out[t] = df
        except Exception:
            pass
    return out


def spark_series(daily: pd.DataFrame, weeks: int = SPARK_WEEKS) -> Optional[Dict[str, Any]]:
    """Weekly (W-FRI) OHLC of the last `weeks` weeks for the list mini candlestick chart:
    {w0: first week end, lo, hi, n, q: base64 of n*4 bytes (o,h,l,c per week, each quantized 0..255 between lo and hi)}."""
    import base64
    need = {"Open", "High", "Low", "Close"}
    if daily is None or daily.empty or not need.issubset(daily.columns):
        return None
    d = daily[list(need)].dropna()
    wk = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna().iloc[-weeks:]
    if len(wk) < 2:
        return None
    lo, hi = float(wk["Low"].min()), float(wk["High"].max())
    dec = 2 if lo >= 1 else 4
    span = (hi - lo) or 1.0
    q = bytearray()
    for o, h, l, c in wk[["Open", "High", "Low", "Close"]].itertuples(index=False):
        q += bytes(max(0, min(SPARK_Q, int(round((float(v) - lo) / span * SPARK_Q)))) for v in (o, h, l, c))
    return {"w0": wk.index[0].strftime("%Y-%m-%d"), "lo": round(lo, dec), "hi": round(hi, dec), "n": len(wk),
            "q": base64.b64encode(bytes(q)).decode()}


def spark_ma(bars: List[list], weeks: int) -> Optional[Dict[str, Any]]:
    """Daily SMA 50/100/150/200 sampled at each week's last trading day, for the last `weeks` weekly bars of the mini chart:
    {lo, hi, q: base64 of weeks*4 bytes (sma50, sma100, sma150, sma200 per week; 0..254 between lo and hi, 255 = none)}."""
    import base64
    from srs_app.fib import sma_weekly, SMA_PERIODS
    if not bars:
        return None
    sm = sma_weekly(bars)
    rows = list(zip(*(sm[n] for n in SMA_PERIODS)))[-weeks:]
    if len(rows) != weeks:
        return None
    vals = [v for r in rows for v in r if v is not None]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    q = bytes(255 if v is None else max(0, min(254, int(round((v - lo) / span * 254)))) for r in rows for v in r)
    dec = 2 if lo >= 1 else 4
    return {"lo": round(lo, dec), "hi": round(hi, dec), "q": base64.b64encode(q).decode()}


def spark_ema(daily: pd.DataFrame, sp: Dict[str, Any], span: int = 30) -> Optional[str]:
    """Weekly (W-FRI) EMA(span) of closes for the spark's weeks, computed on the whole daily history (so the first
    weeks are warmed up), quantized like the spark OHLC (0..254 between sp lo / hi, clamped; 255 = none); base64."""
    import base64
    wk = daily["Close"].dropna().resample("W-FRI").last().dropna()
    if len(wk) < 2:
        return None
    ema = wk.ewm(span=span, adjust=False).mean().iloc[-int(sp["n"]):]
    if len(ema) != int(sp["n"]):
        return None
    span_ = (float(sp["hi"]) - float(sp["lo"])) or 1.0
    q = bytes(255 if pd.isna(v) else max(0, min(254, int(round((float(v) - float(sp["lo"])) / span_ * 254)))) for v in ema)
    return base64.b64encode(q).decode()


def calibration_tickers(out: Path) -> List[str]:
    """Tickers of the trend-calibration page (app/data/calibration.json, Eyal 2026-10-26); [] when absent."""
    try:
        return sorted({str(r["ticker"]).upper() for r in json.loads((out / "calibration.json").read_text())})
    except Exception:
        return []


def attach_fib(rows: List[Dict[str, Any]], fib: Dict[str, Dict[str, Any]], manual: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
    """fib_* columns (informational, not a PASS gate): anchor low/high (+ daily dates), weekly ATR, and confluence of the
    key levels 0.382 / 0.5 / 0.618 with the current price and with the exported zone (srs_app.fib).
    manual = Eyal's anchors from the app ({ticker: {low, low_date, high, high_date}}, sync.fib_anchors_from_state);
    they replace the automatic anchor (fib_manual = True); the weekly ATR stays the automatic one."""
    from srs_app.fib import fib_confluence
    manual = manual or {}
    for r in rows:
        f, m = fib.get(r["ticker"]), manual.get(r["ticker"])
        for k in ("fib_low", "fib_low_date", "fib_high", "fib_high_date", "fib_atr", "fib_price_level", "fib_zone_levels", "fib_confluence"):
            r[k] = None
        r["fib_manual"] = bool(m)
        if m:
            f = {**(f or {"atr_w": r.get("weekly_atr")}), "low": m["low"], "low_date": m["low_date"], "high": m["high"], "high_date": m["high_date"]}
        if not f:
            continue
        r.update(fib_low=f["low"], fib_low_date=f["low_date"], fib_high=f["high"], fib_high_date=f["high_date"], fib_atr=f["atr_w"])
        c = fib_confluence(f["low"], f["high"], f["atr_w"], r.get("current_price"), r.get("tv_zone_top"), r.get("tv_zone_bottom"))
        r["fib_price_level"] = c["price_level"]
        r["fib_zone_levels"] = c["zone_levels"] or None
        parts = ([f"price@{c['price_level']}"] if c["price_level"] is not None else []) + [f"zone@{x}" for x in c["zone_levels"]]
        r["fib_confluence"] = ", ".join(parts) or None


def export_candles(tickers: List[str], out: Path, fetch_missing: Optional[List[str]] = None,
                   fib_out: Optional[Dict[str, Dict[str, Any]]] = None, ema_for: Optional[set] = None) -> int:
    hist = dict(pd.read_pickle(HIST_CACHE))
    miss = [t for t in (fetch_missing or []) if hist.get(t) is None or getattr(hist.get(t), "empty", True)]
    hist.update(_download_missing(miss))
    cdir = out / "candles"
    cdir.mkdir(parents=True, exist_ok=True)
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=int(365.25 * YEARS)))
    n = 0
    wanted = set(tickers)
    spark: Dict[str, Any] = {}
    for t in tickers:
        df = hist.get(t)
        if df is None or getattr(df, "empty", True):
            continue
        d = df.copy()
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(-1)
        d.index = pd.to_datetime(d.index)
        if getattr(d.index, "tz", None) is not None:
            d.index = d.index.tz_localize(None)
        d = d[d.index >= cutoff].dropna(subset=["Open", "High", "Low", "Close"])
        bars = []
        for ts, r in d.iterrows():
            px = [float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])]
            dec = 2 if px[3] >= 1 else 4
            bars.append([ts.strftime("%Y-%m-%d"), *[round(x, dec) for x in px],
                         int(r["Volume"]) if not pd.isna(r["Volume"]) else 0])
        (cdir / f"{t}.json").write_text(json.dumps({"t": t, "d": bars}, separators=(",", ":")))
        sp = spark_series(d)
        if sp:
            ma = spark_ma(bars, sp["n"])
            if ma:
                sp["ma"] = ma
            if ema_for and t in ema_for:
                e = spark_ema(d, sp)  # d = the 5-year daily frame: ~100 weeks of warm-up before the spark window
                if e:
                    sp["ema30"] = e
            spark[t] = sp
        if fib_out is not None:
            try:
                fa = fib_anchor(bars)
            except Exception as e:  # never block the export
                print(f"  [fib] {t}: {e}")
                fa = None
            if fa:
                fib_out[t] = fa
        n += 1
    (out / "spark.json").write_text(json.dumps(spark, separators=(",", ":")))
    # drop files for tickers no longer exported
    for f in cdir.glob("*.json"):
        if f.stem not in wanted:
            f.unlink()
    return n


def attach_week_closes(rows: List[Dict[str, Any]], asof_date: Optional[str] = None, hist: Optional[Dict[str, Any]] = None) -> None:
    """row['wk_closes'] = the last FROM_ABOVE lookback COMPLETED weekly closes (oldest first) so the app can re-check
    f_from_above live against the zone that counts now (Eyal 2026-10-24, USB: back in the zone from below = not
    interesting until a weekly close above the zone top). Same weeks as report_filters.compute_from_above."""
    import sys as _s
    from datetime import date as _d
    root = str(Path(__file__).resolve().parent.parent)
    if root not in _s.path:
        _s.path.insert(0, root)
    import report_filters as rf
    hist = hist if hist is not None else dict(pd.read_pickle(HIST_CACHE))
    rd = _d.fromisoformat(asof_date) if asof_date else _d.today()
    lb = int(rf.CONFIG["from_above_lookback_w"])
    for r in rows:
        df = hist.get(r["ticker"])
        try:
            wk = rf.completed_weekly(df, rd) if df is not None and not getattr(df, "empty", True) else None
        except Exception:
            wk = None
        if wk is None or wk.empty:
            continue
        c = wk["Close"].astype(float).iloc[-lb:]
        r["wk_closes"] = [round(float(x), 2 if float(x) >= 1 else 4) for x in c]
        r["wk_closes_end"] = wk.index[-1].strftime("%Y-%m-%d")


def attach_reversals(rows: List[Dict[str, Any]], asof_date: Optional[str] = None, hist: Optional[Dict[str, Any]] = None,
                     weeks: int = REV_LOOKBACK_WEEKS) -> None:
    """rev_d (daily bars) / rev_w (completed W-FRI weeks) = {kind: date of the most recent candle of that reversal
    shape in the last `weeks` weeks} (shapes = RULES.md 'Reversal shapes': hammer / engulfing / strong_close /
    rejection; no zone gate). The app filters 'reversal candle within X weeks' on the selected kinds."""
    import sys as _s
    from datetime import date as _d
    root = str(Path(__file__).resolve().parent.parent)
    if root not in _s.path:
        _s.path.insert(0, root)
    import report_filters as rf
    import smooth_support_analysis as ssa
    hist = hist if hist is not None else dict(pd.read_pickle(HIST_CACHE))
    rd = _d.fromisoformat(asof_date) if asof_date else _d.today()
    for r in rows:
        df = hist.get(r["ticker"])
        r["rev_d"], r["rev_w"] = {}, {}
        if df is None or getattr(df, "empty", True):
            continue
        try:
            dd = ssa.completed_daily_bars(ssa.flatten_cols(df), as_of=rf._as_of_ts(rd))
            wk = rf.completed_weekly(df, rd)
            r["rev_d"] = rf.last_reversals(dd, weeks * 5)
            r["rev_w"] = rf.last_reversals(wk, weeks)
        except Exception as e:  # never block the export
            print(f"  [reversals] {r['ticker']}: {e}")


def export(repo: Path, report: Path | None = None, include_all: bool = False, report_date: str | None = None) -> Path:
    """Write app/data/* under repo. report = latest.csv to read (default repo/historical-reports/latest.csv)."""
    out = repo / "app" / "data"
    out.mkdir(parents=True, exist_ok=True)
    rows = build_index(repo, include_all, report)
    tv = export_tv(out)
    watch = load_watchlist()
    tickers = sorted({r["ticker"] for r in rows} | set(tv) | set(watch))
    have = {r["ticker"] for r in rows}
    full = None
    for t in tickers:  # TV-drawn / watchlist tickers outside today's candidates still get a list row
        if t not in have:
            if full is None:
                full = {r["ticker"]: r for r in build_index(repo, True, report)}
            r = dict(full.get(t) or {"ticker": t, "status": "OUT", "badges": ["off_screen"], "tv_found": t in tv})
            rows.append(r)
    nsec = attach_sectors(rows)
    if nsec:
        print(f"  [app data] sector/industry fetched for {nsec} tickers")
    fib: Dict[str, Dict[str, Any]] = {}
    calib = calibration_tickers(out)  # trend-calibration page: candles + spark (+ weekly EMA30), no list rows
    n = export_candles(tickers + [t for t in calib if t not in set(tickers)], out, fetch_missing=list(watch) + calib,
                       fib_out=fib, ema_for=set(calib))
    try:
        from srs_app.sync import fib_anchors_from_state
        manual = fib_anchors_from_state(os.environ.get("SRS_APP_STATE", "/workspace/stock-screener/app_state.json"))
    except Exception as e:
        print(f"  [app data] manual fib anchors skipped: {e}")
        manual = {}
    attach_fib(rows, fib, manual)
    attach_week_closes(rows, asof_date=report_date)
    attach_reversals(rows, asof_date=report_date)
    try:
        from srs_app.rules import build_rules
        (out / "rules.json").write_text(json.dumps(build_rules(), ensure_ascii=False, separators=(",", ":")))
    except Exception as e:  # never block the export
        print(f"  [app data] rules.json skipped: {e}")
    with_candles = {f.stem for f in (out / "candles").glob("*.json")}
    for r in rows:
        r["has_candles"] = r["ticker"] in with_candles
    asof = report_date
    try:
        reports = json.loads((repo / "reports.json").read_text())
        asof = asof or (reports[0]["date"] if isinstance(reports, list) and reports else None)
    except Exception:
        pass
    meta = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "report_date": asof, "count": len(rows), "rows": rows}
    (out / "index.json").write_text(json.dumps(meta, separators=(",", ":")))
    print(f"app data: {len(rows)} rows, {n} candle files, {len(tv)} TV drawings -> {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--report", default=None, help="report CSV (default <repo>/historical-reports/latest.csv)")
    ap.add_argument("--date", default=None, help="report date label (default: newest in reports.json)")
    ap.add_argument("--all", action="store_true", help="export every FinViz row, not just candidates")
    a = ap.parse_args()
    export(Path(a.repo), Path(a.report) if a.report else None, a.all, a.date)


if __name__ == "__main__":
    main()
