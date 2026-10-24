"""Export static data for the web app (published to GitHub Pages under /app/data/).

Writes, relative to the repo root:
  app/data/index.json          candidate list (badges + key levels) from historical-reports/latest.csv
  app/data/tv_drawings.json    read-only TradingView drawings (source 'tv') from /workspace/stock-screener/tv_drawings.json
  app/data/candles/<T>.json    daily OHLCV, 5 years, from the scanner's history cache (/workspace/hist_cache.pkl)
  app/data/spark.json          list mini charts: last SPARK_WEEKS weekly (W-FRI) OHLC candles per exported ticker, 1 byte/value

Candidates = PASS ∪ WAIT (badge 'waiting': PASS except a healthy red last week on above-average volume) ∪ needs_drawing ∪ bot review ∪ obsolete (tv_stale) ∪ last-week hammer (gated, see hammer_ok)
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
    "ticker", "status", "current_price", "dollar_vol_30d", "days_to_earnings", "earnings_date",
    "tv_zone_top", "tv_zone_bottom", "tv_entry", "tv_sl", "tv_tp", "tv_rr", "tv_source", "tv_read_date",
    "tv_zone_dist_atr", "tv_stale", "tv_stale_detail", "tv_bot_status", "weekly_atr",
    "f_technical", "f_near_zone", "needs_drawing", "f_bot_review", "f_tv_stale", "f_last_week_reversal",
    "last_week_reversal_kind", "hammer_entry", "hammer_sl", "hammer_tp", "hammer_rr", "hammer_calm_weeks",
    "hammer_score", "inst_own_pct", "short_float_pct", "tradingview_url",
    "f_dollar_vol", "f_history", "f_no_earnings_14d",
    "f_no_red_vol_week", "red_vol_week_date", "red_vol_body_pct", "red_vol_ratio", "red_vol_detail",
]


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
        elif r.get("status") == "WAIT":  # healthy red week on above-avg volume: wait for the weekly close
            badges.append("waiting")
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


def export_candles(tickers: List[str], out: Path, fetch_missing: Optional[List[str]] = None) -> int:
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
            spark[t] = sp
        n += 1
    (out / "spark.json").write_text(json.dumps(spark, separators=(",", ":")))
    # drop files for tickers no longer exported
    for f in cdir.glob("*.json"):
        if f.stem not in wanted:
            f.unlink()
    return n


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
    n = export_candles(tickers, out, fetch_missing=watch)
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
