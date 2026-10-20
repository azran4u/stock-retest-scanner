"""srs command line: fetch / weekly / trend / info."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from .data import DEFAULT_CACHE, fetch_many, load_cached, parse_tickers_file, yf_symbol
from .trend import TREND_DEFAULTS, trend
from .weekly import to_weekly


def _table(rows: List[Dict[str, Any]], cols: List[str]) -> str:
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) if rows else len(c) for c in cols}
    lines = ["  ".join(c.ljust(w[c]) for c in cols), "  ".join("-" * w[c] for c in cols)]
    lines += ["  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols) for r in rows]
    return "\n".join(lines)


def _tickers(arg: str) -> List[str]:
    p = Path(arg).expanduser()
    return parse_tickers_file(p) if p.exists() else [yf_symbol(t) for t in arg.split(",") if t.strip()]


def _maybe_fetch(tickers: List[str], args) -> None:
    if getattr(args, "fetch", False):
        r = fetch_many(tickers, years=args.years, cache_dir=args.cache_dir, log=lambda m: print(m, file=sys.stderr))
        print(r.summary(), file=sys.stderr)


def cmd_fetch(args) -> int:
    tickers = parse_tickers_file(args.tickers_file)
    print(f"{len(tickers)} tickers -> {Path(args.cache_dir).expanduser()}")
    r = fetch_many(tickers, years=args.years, cache_dir=args.cache_dir)
    print(r.summary())
    return 0 if not r.failed else 1


def cmd_weekly(args) -> int:
    t = yf_symbol(args.ticker)
    _maybe_fetch([t], args)
    d = load_cached(t, args.cache_dir)
    if d is None:
        print(f"{t}: not in cache; run `srs fetch` first (or pass --fetch)", file=sys.stderr)
        return 1
    w = to_weekly(d, asof=args.asof, drop_incomplete=not args.include_incomplete)
    if args.last:
        w = w.tail(args.last)
    if args.json:
        recs = [{"week": i.strftime("%Y-%m-%d"), **{c: float(v) for c, v in r.items()}} for i, r in w.iterrows()]
        print(json.dumps(recs, indent=1))
    else:
        out = w.copy()
        out.index = out.index.strftime("%Y-%m-%d")
        out.index.name = "week"
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(out.round(2).to_string())
    return 0


def _trend_params(args) -> Dict[str, Any]:
    p: Dict[str, Any] = {}
    for k, v in TREND_DEFAULTS.items():
        a = getattr(args, k, None)
        if a is not None:
            p[k] = (a.lower() in ("1", "true", "yes", "y")) if isinstance(v, bool) else type(v)(a)
    return p


def cmd_trend(args) -> int:
    tickers = _tickers(args.tickers_file)
    _maybe_fetch(tickers, args)
    params = _trend_params(args)
    rows, out = [], []
    for t in tickers:
        d = load_cached(t, args.cache_dir)
        if d is None:
            rows.append({"ticker": t, "trend": "?", "reason": "not in cache (run srs fetch)"})
            out.append({"ticker": t, "trend": None, "reason": "not in cache"})
            continue
        w = to_weekly(d, asof=args.asof, drop_incomplete=not args.include_incomplete)
        r = trend(w, **params)
        u = r.get("used") or {}
        fmt = lambda v: " -> ".join(f"{x:g}" for x in v) if v else ""
        rows.append({"ticker": t, "trend": r["trend"], "last_week": w.index[-1].strftime("%Y-%m-%d") if len(w) else "",
                     "highs": fmt(u.get("highs")), "lows": fmt(u.get("lows")), "reason": r["reason"]})
        out.append({"ticker": t, "asof": args.asof, **r})
    if args.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        print(_table(rows, ["ticker", "trend", "last_week", "highs", "lows", "reason"]))
    return 0


def cmd_info(args) -> int:
    from .info import info
    rows = [info(t) for t in _tickers(args.tickers)]
    if args.json:
        print(json.dumps(rows, indent=1, default=str))
    else:
        print(_table(rows, ["ticker", "inst_own", "short_float", "sector", "market_cap", "next_earnings"]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="srs", description="stock-retest-scanner building blocks")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, fetch_opt=True):
        p.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="daily CSV cache (default ~/.srs_cache)")
        p.add_argument("--years", type=int, default=5, help="history to keep (default 5)")
        if fetch_opt:
            p.add_argument("--fetch", action="store_true", help="update the cache first")
            p.add_argument("--asof", default=None, help="cut data at this date (YYYY-MM-DD)")
            p.add_argument("--include-incomplete", action="store_true",
                           help="keep the in-progress week (default: completed weeks only)")
            p.add_argument("--json", action="store_true", help="JSON output")

    p = sub.add_parser("fetch", help="download / update the daily OHLCV cache")
    p.add_argument("tickers_file")
    common(p, fetch_opt=False)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("weekly", help="weekly W-FRI candles for one ticker")
    p.add_argument("ticker")
    p.add_argument("--last", type=int, default=20, help="show the last N weeks (0 = all)")
    common(p)
    p.set_defaults(func=cmd_weekly)

    p = sub.add_parser("trend", help="primary weekly trend (up / down / none)")
    p.add_argument("tickers_file", help="tickers file, or a comma list like AAPL,MSFT")
    common(p)
    for k, v in TREND_DEFAULTS.items():
        p.add_argument("--" + k.replace("_", "-"), dest=k, default=None, help=f"default {v}")
    p.set_defaults(func=cmd_trend)

    p = sub.add_parser("info", help="inst own / short float / sector / market cap / next earnings")
    p.add_argument("tickers", help="tickers file or comma list")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
