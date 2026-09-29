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
  python tv_drawings.py merge [--report CSV ...] [--today YYYY-MM-DD]
        -> adds tv_found, tv_zone_top, tv_zone_bottom, tv_entry, tv_sl, tv_tp, tv_rr,
           tv_read_date to latest.csv + the dated copy (default: latest.csv and the
           dated CSV identical to it)
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
TZ = ZoneInfo("Asia/Jerusalem")

TARGET_FILTERS = ["f_dollar_vol", "f_short_float", "f_no_earnings_14d", "f_history", "f_smooth_streak"]
TV_COLS = ["tv_found", "tv_zone_top", "tv_zone_bottom", "tv_entry", "tv_sl", "tv_tp", "tv_rr", "tv_read_date"]
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


def upsert(ticker: str, found: bool, symbol: Optional[str] = None, read_at: Optional[str] = None,
           **vals: Optional[float]) -> Dict[str, Any]:
    t = ticker.strip().upper()
    if ":" in t:
        symbol, t = t, t.split(":", 1)[1]
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
    store[t] = rec
    save_store(store)
    return rec


def merge_df(df: pd.DataFrame, today: Optional[date] = None,
             store: Optional[Dict[str, Dict[str, Any]]] = None) -> pd.DataFrame:
    """Add TV_COLS: filled only for today's target set; found=yes/no; '' = not checked."""
    today = today or _today()
    store = load_store() if store is None else store
    df = df.copy()
    for c in TV_COLS:
        df[c] = pd.Series([""] * len(df), index=df.index, dtype=object)
    targets = set(target_rows(df, today)["ticker"].astype(str))
    for i, r in df.iterrows():
        t = str(r["ticker"])
        rec = store.get(t)
        if t not in targets or not rec:
            continue
        df.at[i, "tv_read_date"] = rec.get("read_date") or ""
        if not rec.get("found"):
            df.at[i, "tv_found"] = "no"
            continue
        df.at[i, "tv_found"] = "yes"
        for k in ("zone_top", "zone_bottom", "entry", "sl", "tp", "rr"):
            v = rec.get(k)
            df.at[i, f"tv_{k}"] = "" if v is None else f"{float(v):g}"
    return place_tv_cols(apply_tv_rr_filter(df))


def apply_tv_rr_filter(df: pd.DataFrame) -> pd.DataFrame:
    """f_rr now = TradingView drawing found AND TV R:R >= RR_MIN ("not found" fails).

    The scanner-computed value is preserved as f_rr_computed (internal only).
    `status` is NOT recomputed here: it was set by report_filters from the computed
    rr (f_rr_computed) and stays that way until the user approves the switch.
    """
    if "f_rr_computed" not in df.columns:
        src = df["f_rr"] if "f_rr" in df.columns else pd.Series([False] * len(df), index=df.index)
        df["f_rr_computed"] = src.map(_truthy)
    def tv_ok(r: pd.Series) -> bool:
        if str(r.get("tv_found")) != "yes":
            return False
        try:
            return float(r.get("tv_rr")) >= RR_MIN
        except (TypeError, ValueError):
            return False
    df["f_rr"] = df.apply(tv_ok, axis=1)
    return df


def place_tv_cols(df: pd.DataFrame) -> pd.DataFrame:
    """tv_* columns go right before smooth_streak_weeks (after the computed levels)."""
    cols = [c for c in df.columns if c not in TV_COLS and c != "f_rr_computed"]
    if "f_rr_computed" in df.columns:
        cols.insert(cols.index("f_rr") + 1 if "f_rr" in cols else len(cols), "f_rr_computed")
    anchor = "smooth_streak_weeks" if "smooth_streak_weeks" in cols else "tradingview_url"
    pos = cols.index(anchor) if anchor in cols else len(cols)
    cols[pos:pos] = [c for c in TV_COLS if c in df.columns]
    return df[cols]


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


def merge_files(paths: List[Path], today: date) -> None:
    for p in paths:
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        base = df[[c for c in df.columns if c not in TV_COLS]]
        if "f_rr_computed" in base.columns:  # re-merge: restore the computed flag first
            base = base.assign(f_rr=base["f_rr_computed"]).drop(columns=["f_rr_computed"])
        out = merge_df(base, today)
        out.to_csv(p, index=False)
        n_yes = int((out["tv_found"] == "yes").sum())
        n_no = int((out["tv_found"] == "no").sum())
        print(f"merged {p}: tv_found yes={n_yes} no={n_no}")


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
    m = sub.add_parser("merge", help="merge store into report CSV(s)")
    m.add_argument("--report", type=Path, action="append", default=None)
    m.add_argument("--today", default=None)
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
        else:
            vals = {"zone_top": args.zone_top, "zone_bottom": args.zone_bottom, "entry": args.entry,
                    "sl": args.sl, "tp": args.tp, "rr": args.rr}
            missing = [k for k, v in vals.items() if v is None]
            if missing:
                ap.error(f"missing values: {', '.join(missing)} (or pass --not-found)")
            rec = upsert(args.ticker, True, read_at=args.read_at, **vals)
        print(json.dumps({args.ticker.upper(): rec}, indent=2))
    elif args.cmd == "merge":
        today = date.fromisoformat(args.today) if args.today else _today()
        merge_files(args.report or _default_reports(), today)
    elif args.cmd == "show":
        st = load_store()
        print(json.dumps(st.get(args.ticker.upper()) if args.ticker else st, indent=2))


if __name__ == "__main__":
    main()
