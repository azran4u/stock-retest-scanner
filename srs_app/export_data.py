"""Export static data for the web app (published to GitHub Pages under /app/data/).

Writes, relative to the repo root:
  app/data/index.json          candidate list (badges + key levels) from historical-reports/latest.csv
  app/data/tv_drawings.json    read-only TradingView drawings (source 'tv') from /workspace/stock-screener/tv_drawings.json
  app/data/candles/<T>.json    daily OHLCV, 5 years, from the scanner's history cache (/workspace/hist_cache.pkl)

Candidates = PASS ∪ needs_drawing ∪ bot review ∪ obsolete (tv_stale) ∪ last-week hammer
             ∪ any TradingView drawing found ∪ open positions.

Usage:  python -m srs_app.export_data [--repo .] [--all]
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

HIST_CACHE = Path(os.environ.get("SRS_HIST_CACHE", "/workspace/hist_cache.pkl"))
TV_DRAWINGS = Path(os.environ.get("SRS_TV_DRAWINGS", "/workspace/stock-screener/tv_drawings.json"))
YEARS = 5

INDEX_COLS = [
    "ticker", "status", "current_price", "dollar_vol_30d", "days_to_earnings", "earnings_date",
    "tv_zone_top", "tv_zone_bottom", "tv_entry", "tv_sl", "tv_tp", "tv_rr", "tv_source", "tv_read_date",
    "tv_zone_dist_atr", "tv_stale", "tv_stale_detail", "tv_bot_status", "weekly_atr",
    "f_technical", "f_near_zone", "needs_drawing", "f_bot_review", "f_tv_stale", "f_last_week_reversal",
    "last_week_reversal_kind", "hammer_entry", "hammer_sl", "hammer_tp", "hammer_rr", "hammer_calm_weeks",
    "hammer_score", "inst_own_pct", "short_float_pct", "tradingview_url",
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
        if _truthy(r.get("needs_drawing")):
            badges.append("needs_drawing")
        if _truthy(r.get("f_bot_review")):
            badges.append("review")
        if _truthy(r.get("f_tv_stale")):
            badges.append("obsolete")
        if _truthy(r.get("f_last_week_reversal")):
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


def export_candles(tickers: List[str], out: Path) -> int:
    hist = pd.read_pickle(HIST_CACHE)
    cdir = out / "candles"
    cdir.mkdir(parents=True, exist_ok=True)
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=int(365.25 * YEARS)))
    n = 0
    wanted = set(tickers)
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
        n += 1
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
    tickers = sorted({r["ticker"] for r in rows} | set(tv))
    have = {r["ticker"] for r in rows}
    for t in tickers:  # TV-drawn tickers that fell out of today's screen still get a list row
        if t not in have:
            rows.append({"ticker": t, "status": "OUT", "badges": ["off_screen"], "tv_found": True})
    n = export_candles(tickers, out)
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
