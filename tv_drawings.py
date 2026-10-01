#!/usr/bin/env python3
"""TradingView drawings store + report merge (read-only source of zone/entry/SL/TP/R:R).

The user's TradingView drawings are the source of truth for the trade levels:
a Rectangle = zone (top/bottom) and a Long Position tool = entry / stop / target
and TradingView's R:R. A browser agent READS them daily (never edits, moves or
deletes a drawing) and records the values here.

Store: /workspace/stock-screener/tv_drawings.json, keyed by ticker:
  {"ST": {"found": true, "zone_top": 41.96, "zone_bottom": 41.31, "entry": 42.11,
          "sl": 38.46, "tp": 51.55, "rr": 2.59, "read_at": "...", "read_date": "YYYY-MM-DD",
          "symbol": "NYSE:ST"}}

Daily target set = report rows passing f_dollar_vol AND f_short_float AND
f_no_earnings_14d (evaluated LIVE vs today from the cached earnings date, same as
the dashboard) AND f_history AND f_smooth_streak.

Usage:
  python tv_drawings.py targets [--report CSV] [--today YYYY-MM-DD]
        -> /workspace/tv_read_targets.txt (EXCHANGE:TICKER per line) + .json
  python tv_drawings.py upsert ST --zone-top 41.96 --zone-bottom 41.31 \\
        --entry 42.11 --sl 38.46 --tp 51.55 --rr 2.59 [--read-at ISO]
  python tv_drawings.py upsert XYZ --not-found
  python tv_drawings.py upsert NYSE:ST ...values... --screenshot /workspace/tv_shots/ST.png
        -> charts/latest/ST.webp in the repo (<=1280px, <300KB, overwritten) + store
           fields screenshot / screenshot_at / screenshot_date
  python tv_drawings.py screenshot NYSE:ST /workspace/tv_shots/ST.png   (image only)
  python tv_drawings.py merge [--report CSV ...] [--no-grok-target]
        -> writes tv_found, tv_zone_top, tv_zone_bottom, tv_entry, tv_sl, tv_tp, tv_rr,
           tv_read_date (latest stored reading per ticker) into latest.csv + its dated
           twin, sets f_rr = found AND tv_rr >= 2, recomputes status / failed_filters /
           reason, and regenerates /workspace/stock-screener/grok_sync_target.{json,txt}
  python tv_drawings.py show [TICKER]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

_HERE = Path(__file__).resolve().parent
for _d in (_HERE, Path("/workspace/publish-stock-retest-scanner"), Path("/workspace")):
    if str(_d) not in sys.path and (_d / "report_filters.py").exists():
        sys.path.insert(0, str(_d))
        break

STORE = Path("/workspace/stock-screener/tv_drawings.json")
REPO = Path("/workspace/publish-stock-retest-scanner")
LATEST = REPO / "historical-reports" / "latest.csv"
TARGETS_TXT = Path("/workspace/tv_read_targets.txt")
TARGETS_JSON = Path("/workspace/tv_read_targets.json")
GROK_TARGET_DIR = Path("/workspace/stock-screener")  # grok_sync_target.{json,txt}
# Chart screenshots: ONE current image per ticker, overwritten on each read (no history).
CHARTS_DIR = REPO / "charts" / "latest"
SHOT_MAX_WIDTH = 1280
SHOT_MAX_BYTES = 300_000
TZ = ZoneInfo("Asia/Jerusalem")

TARGET_FILTERS = ["f_dollar_vol", "f_short_float", "f_no_earnings_14d", "f_history", "f_smooth_streak"]
TV_COLS = ["tv_found", "tv_zone_top", "tv_zone_bottom", "tv_entry", "tv_sl", "tv_tp", "tv_rr", "tv_read_date",
           "tv_screenshot"]
EARNINGS_BLACKOUT_DAYS = 14  # same as stock_screen.EARNINGS_BLACKOUT_DAYS / dashboard
RR_MIN = 2.0  # same as stock_screen.RR_MIN / report_filters CONFIG["rr_min"]
try:
    import stock_screen as _ss  # noqa: E402

    RR_MIN = float(_ss.RR_MIN)
except Exception:
    pass


def _today() -> date:
    return datetime.now(TZ).date()


def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def _symbol(row: pd.Series) -> str:
    m = re.search(r"symbol=([^&]+)", str(row.get("tradingview_url") or ""))
    return m.group(1) if m else str(row["ticker"]).upper().replace("-", ".")


def _earn_cached(ticker: str) -> Optional[str]:
    try:
        d = json.loads((Path("/workspace/cache") / f"earn_{ticker.strip().upper()}.json").read_text())
        return str(d.get("earnings_date") or "")[:10] or None
    except Exception:
        return None


def no_earnings_live(ticker: str, row_date: Any, today: date) -> bool:
    """Live f_no_earnings_14d: earliest known future date (earnings cache, then the
    report's earnings_date); unknown / already passed -> False."""
    for cand in (_earn_cached(ticker), row_date):
        if cand is None or str(cand).strip() in ("", "nan", "None"):
            continue
        try:
            d = date.fromisoformat(str(cand)[:10])
        except Exception:
            continue
        if d >= today:
            return (d - today).days >= EARNINGS_BLACKOUT_DAYS
    return False


def target_rows(df: pd.DataFrame, today: date) -> pd.DataFrame:
    live = df.apply(lambda r: no_earnings_live(str(r["ticker"]), r.get("earnings_date"), today), axis=1)
    mask = live.astype(bool)
    for f in TARGET_FILTERS:
        if f == "f_no_earnings_14d":
            continue
        mask &= df[f].map(_truthy)
    out = df[mask].copy()
    out["tv_symbol"] = out.apply(_symbol, axis=1)
    return out


def load_store() -> Dict[str, Dict[str, Any]]:
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return {}


def save_store(store: Dict[str, Dict[str, Any]]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(dict(sorted(store.items())), indent=2) + "\n")


def csv_ticker(ticker: str) -> str:
    """Store / CSV / filename spelling: 'NYSE:MOG.A' -> 'MOG-A'."""
    t = ticker.strip().upper()
    if ":" in t:
        t = t.split(":", 1)[1]
    return t.replace(".", "-")


def save_screenshot(ticker: str, src: Path) -> str:
    """Resize (<= SHOT_MAX_WIDTH px wide) + compress `src` into CHARTS_DIR/<TICKER>.webp
    (overwrites; removes any other-format copy of the same ticker). Returns the
    repo-relative path, e.g. 'charts/latest/MOG-A.webp'."""
    from PIL import Image

    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"screenshot not found: {src}")
    t = csv_ticker(ticker)
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = CHARTS_DIR / f"{t}.webp"
    with Image.open(src) as im:
        im = im.convert("RGB")
        if im.width > SHOT_MAX_WIDTH:
            im = im.resize((SHOT_MAX_WIDTH, round(im.height * SHOT_MAX_WIDTH / im.width)), Image.LANCZOS)
        for q in (80, 70, 60, 50, 40):
            im.save(dest, "WEBP", quality=q, method=6)
            if dest.stat().st_size <= SHOT_MAX_BYTES:
                break
        while dest.stat().st_size > SHOT_MAX_BYTES and im.width > 640:
            im = im.resize((int(im.width * 0.85), int(im.height * 0.85)), Image.LANCZOS)
            im.save(dest, "WEBP", quality=50, method=6)
    for old in CHARTS_DIR.glob(f"{t}.*"):
        if old != dest:
            old.unlink()
    return dest.relative_to(REPO).as_posix()


def remove_screenshot(ticker: str) -> None:
    for old in CHARTS_DIR.glob(f"{csv_ticker(ticker)}.*"):
        old.unlink()


def upsert(ticker: str, found: bool, symbol: Optional[str] = None, read_at: Optional[str] = None,
           screenshot: Optional[Path] = None, **vals: Optional[float]) -> Dict[str, Any]:
    t = ticker.strip().upper()
    if ":" in t:
        symbol = t
    t = csv_ticker(t)
    ts = datetime.fromisoformat(read_at) if read_at else datetime.now(TZ)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=TZ)
    rec: Dict[str, Any] = {"found": bool(found)}
    for k in ("zone_top", "zone_bottom", "entry", "sl", "tp", "rr"):
        rec[k] = (float(vals[k]) if vals.get(k) is not None else None) if found else None
    rec["read_at"] = ts.isoformat(timespec="seconds")
    rec["read_date"] = ts.astimezone(TZ).date().isoformat()
    if symbol:
        rec["symbol"] = symbol
    store = load_store()
    prev = store.get(t) or {}
    if not found:
        remove_screenshot(t)  # no drawing -> no card -> keep the repo small
    elif screenshot is not None:
        rec["screenshot"] = save_screenshot(t, screenshot)
        rec["screenshot_at"] = rec["read_at"]
        rec["screenshot_date"] = rec["read_date"]
    elif prev.get("screenshot") and (REPO / prev["screenshot"]).exists():
        for k in ("screenshot", "screenshot_at", "screenshot_date"):  # keep the last image
            if k in prev:
                rec[k] = prev[k]
    store[t] = rec
    save_store(store)
    return rec


def _hist_upto(hist_map: Dict[str, Any], ticker: str, report_date: Optional[date]) -> Optional[pd.DataFrame]:
    """Cached daily OHLCV for `ticker` cut at report_date (same prep as report_filters)."""
    import stock_screen as ss

    raw = hist_map.get(ticker) if hist_map else None
    need = ["Open", "High", "Low", "Close", "Volume"]
    if raw is None or getattr(raw, "empty", True):
        return None
    try:
        d = ss._normalize_ohlcv_index(raw)
        if not all(c in d.columns for c in need):
            return None
        if report_date is not None:
            d = d[d.index.normalize() <= pd.Timestamp(report_date)]
        d = d[need].dropna()
        return d if len(d) else None
    except Exception:
        return None


def _csv_val(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    return str(v)


def merge_df(df: pd.DataFrame, today: Optional[date] = None,
             store: Optional[Dict[str, Dict[str, Any]]] = None,
             report_date: Optional[date] = None,
             hist_map: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Apply the store to a report frame and recompute status.

    tv_* = the latest stored reading for each ticker (any ticker with a reading;
    tv_found yes / no, '' = never read). f_rr = found AND tv_rr >= rr_min, then
    status / failed_filters / reason are recomputed from the core filters
    (report_filters.finalize_status / status_reason). `today` is unused (kept for
    backwards-compatible calls). Also refreshes the price-vs-zone columns
    (tv_price, tv_weekly_atr, tv_zone_dist, tv_zone_dist_atr, f_near_zone) from the
    cached daily history (`hist_map`, default /workspace/hist_cache.pkl) as of
    `report_date` (default: the report's own date column is absent -> today).
    """
    import report_filters as rf
    import stock_screen as ss

    if hist_map is None:
        hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    report_date = report_date or _today()

    store = load_store() if store is None else store
    store = {str(k).strip().upper(): v for k, v in store.items()}
    df = df.copy()
    if "f_rr_computed" not in df.columns:  # pre-TV report: old f_rr was the computed flag
        df["f_rr_computed"] = df["f_rr"] if "f_rr" in df.columns else False
    for c in TV_COLS + rf.NEAR_ZONE_COLS + rf.INFO_FILTERS:
        df[c] = pd.Series([""] * len(df), index=df.index, dtype=object)
    for c in ("f_rr", "status", "failed_filters", "reason", "needs_drawing"):
        df[c] = df[c].astype(object) if c in df.columns else pd.Series([""] * len(df), index=df.index, dtype=object)
    for i, row in df.iterrows():
        r = {k: row[k] for k in df.columns}
        rf.apply_tv(r, store.get(str(row["ticker"]).strip().upper()))
        rf.finalize_status(r)
        reason = rf.status_reason(r, row.get("reason"))
        for c in TV_COLS + ["f_rr", "status", "failed_filters"]:
            df.at[i, c] = r[c]
        df.at[i, "needs_drawing"] = _csv_val(rf.compute_needs_drawing(r))
        nz = rf.compute_near_zone(_hist_upto(hist_map, str(row["ticker"]).strip(), report_date), r)
        for c, v in nz.items():
            df.at[i, c] = _csv_val(v)
        notes = [n for n in str(row.get("filter_notes") or "").split("; ")
                 if n and "(f_rr False)" not in n]
        if not r["f_rr"]:
            notes.append(rf.tv_note(r))
        if "filter_notes" in df.columns:
            df.at[i, "filter_notes"] = "; ".join(notes)
        df.at[i, "reason"] = reason
    return place_tv_cols(df)


def place_tv_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Column order = report_filters.REPORT_COLS for known columns, extras kept after."""
    import report_filters as rf

    known = [c for c in rf.REPORT_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in rf.REPORT_COLS]
    return df[known + extra]


def _default_reports() -> List[Path]:
    """latest.csv plus the dated CSV that is byte-identical to it (the day's twin)."""
    out = [LATEST]
    if LATEST.exists():
        data = LATEST.read_bytes()
        for p in sorted(LATEST.parent.glob("????-??-??.csv"), reverse=True):
            if p.read_bytes() == data:
                out.append(p)
                break
    return out


def _report_date(paths: List[Path]) -> str:
    for p in paths:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem):
            return p.stem
    return _today().isoformat()


def merge_files(paths: List[Path], grok_target: bool = True) -> None:
    """Merge the store into each CSV, recompute status, then regenerate grok_sync_target
    from the first (latest) report's status=PASS rows."""
    import stock_screen as ss

    first = None
    rd = date.fromisoformat(_report_date(paths))
    hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    for p in paths:
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        base = df[[c for c in df.columns if c not in TV_COLS]]
        out = merge_df(base, report_date=rd, hist_map=hist_map)
        out.to_csv(p, index=False)
        first = out if first is None else first
        n_yes = int((out["tv_found"] == "yes").sum())
        n_no = int((out["tv_found"] == "no").sum())
        n_pass = int((out["status"] == "PASS").sum())
        n_near = int((out["f_near_zone"] == "True").sum())
        n_near_pass = int(((out["f_near_zone"] == "True") & (out["status"] == "PASS")).sum())
        n_nd = int((out["needs_drawing"] == "True").sum())
        print(f"merged {p} (as of {rd}): tv_found yes={n_yes} no={n_no}; status PASS={n_pass}; "
              f"f_near_zone={n_near} (PASS {n_near_pass}); needs_drawing={n_nd}")
    if grok_target and first is not None:
        from export_daily_report import write_grok_target, write_needs_drawing_target

        gp = write_grok_target(first, _report_date(paths), GROK_TARGET_DIR)
        print(f"grok target {gp}: {json.loads(gp.read_text())['symbols']}")
        np_ = write_needs_drawing_target(first, _report_date(paths), GROK_TARGET_DIR)
        print(f"needs-drawing target {np_}: {json.loads(np_.read_text())['symbols']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("targets", help="write the day's read-target list")
    a.add_argument("--report", type=Path, default=LATEST)
    a.add_argument("--today", default=None)
    a.add_argument("--out-txt", type=Path, default=TARGETS_TXT)
    a.add_argument("--out-json", type=Path, default=TARGETS_JSON)
    u = sub.add_parser("upsert", help="record one ticker's TradingView drawing values")
    u.add_argument("ticker", help="TICKER or EXCHANGE:TICKER")
    u.add_argument("--not-found", action="store_true", help="no drawing found on the chart")
    for k in ("zone-top", "zone-bottom", "entry", "sl", "tp", "rr"):
        u.add_argument(f"--{k}", type=float, default=None)
    u.add_argument("--read-at", default=None, help="ISO datetime of the read (default now, Asia/Jerusalem)")
    u.add_argument("--screenshot", type=Path, default=None,
                   help="chart screenshot (PNG/JPG/WebP on the box); resized <=1280px, WebP <300KB, "
                        "stored as charts/latest/<TICKER>.webp in the repo (overwritten each read)")
    sc = sub.add_parser("screenshot", help="attach/replace only the chart screenshot (values unchanged)")
    sc.add_argument("ticker")
    sc.add_argument("path", type=Path)
    m = sub.add_parser("merge", help="merge store into report CSV(s)")
    m.add_argument("--report", type=Path, action="append", default=None)
    m.add_argument("--today", default=None, help="ignored (kept for compatibility)")
    m.add_argument("--no-grok-target", action="store_true", help="don't regenerate grok_sync_target")
    s = sub.add_parser("show")
    s.add_argument("ticker", nargs="?")
    args = ap.parse_args()

    if args.cmd == "targets":
        today = date.fromisoformat(args.today) if args.today else _today()
        df = pd.read_csv(args.report)
        tr = target_rows(df, today)
        syms = tr["tv_symbol"].tolist()
        args.out_txt.write_text("\n".join(syms) + ("\n" if syms else ""))
        args.out_json.write_text(json.dumps({
            "date": today.isoformat(),
            "report": str(args.report),
            "filters": TARGET_FILTERS,
            "note": "f_no_earnings_14d evaluated live vs date (cached earnings date)",
            "count": len(syms),
            "targets": [{"ticker": r.ticker, "symbol": r.tv_symbol, "status": r.status,
                         "smooth_streak_weeks": None if pd.isna(r.smooth_streak_weeks) else int(r.smooth_streak_weeks)}
                        for r in tr.itertuples()],
        }, indent=2) + "\n")
        print(f"{len(syms)} targets -> {args.out_txt}, {args.out_json}")
    elif args.cmd == "upsert":
        if args.not_found:
            rec = upsert(args.ticker, False, read_at=args.read_at)
            if args.screenshot:
                print("note: --screenshot ignored for --not-found (no card without a drawing)")
        else:
            vals = {"zone_top": args.zone_top, "zone_bottom": args.zone_bottom, "entry": args.entry,
                    "sl": args.sl, "tp": args.tp, "rr": args.rr}
            missing = [k for k, v in vals.items() if v is None]
            if missing:
                ap.error(f"missing values: {', '.join(missing)} (or pass --not-found)")
            rec = upsert(args.ticker, True, read_at=args.read_at, screenshot=args.screenshot, **vals)
        print(json.dumps({csv_ticker(args.ticker): rec}, indent=2))
    elif args.cmd == "screenshot":
        t = csv_ticker(args.ticker)
        store = load_store()
        if not (store.get(t) or {}).get("found"):
            ap.error(f"{t}: no found drawing in the store; upsert the values first")
        rel = save_screenshot(t, args.path)
        now = datetime.now(TZ)
        store[t].update({"screenshot": rel, "screenshot_at": now.isoformat(timespec="seconds"),
                         "screenshot_date": now.date().isoformat()})
        save_store(store)
        print(json.dumps({t: store[t]}, indent=2))
    elif args.cmd == "merge":
        merge_files(args.report or _default_reports(), grok_target=not args.no_grok_target)
    elif args.cmd == "show":
        st = load_store()
        print(json.dumps(st.get(args.ticker.upper()) if args.ticker else st, indent=2))


if __name__ == "__main__":
    main()
