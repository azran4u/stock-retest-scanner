#!/usr/bin/env python3
"""Manage Eyal's open/closed positions (positions.json) and refresh their market data.

  python positions.py list
  python positions.py add SWK --qty 1 --entry 88.68 --stop 82.27 [--target 102.48] [--date 2026-10-12] [--exchange NYSE] [--note ...]
  python positions.py set SWK --stop 85 --target 105        # edit an open position
  python positions.py close SWK --price 101.5 [--date ...]  # mark closed (kept for history)
  python positions.py refresh                               # fetch latest daily bar + weekly ATR(14) (run by the daily export)
  python positions.py check [--no-refresh] [--json]         # alert check; exit 2 if any flag fires

Dashboard (index.html / table.html via positions.js) reads positions.json; all P/L, R and distance
numbers are computed from the stored `market` block (close, low, high, weekly_atr).
Near = within 0.5 weekly ATR (NEAR_ATR). Hit = daily low <= stop / daily high >= target.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PATH = Path(__file__).resolve().parent / "positions.json"
NEAR_ATR = 0.5
TZ = ZoneInfo("Asia/Jerusalem")


def load(path: Path = PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"positions": []}


def save(d: dict, path: Path = PATH) -> None:
    d["updated_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    path.write_text(json.dumps(d, indent=2) + "\n")


def find_open(d: dict, ticker: str) -> dict:
    for p in d["positions"]:
        if p["ticker"] == ticker.upper() and p.get("status", "open") == "open":
            return p
    sys.exit(f"no open position for {ticker}")


def fetch_market(ticker: str) -> dict:
    import yfinance as yf

    sym = ticker.replace(".", "-")
    t = yf.Ticker(sym)
    d = t.history(period="1mo", interval="1d", auto_adjust=False)
    w = t.history(period="1y", interval="1wk", auto_adjust=False)
    if d.empty:
        raise RuntimeError(f"no daily data for {ticker}")
    last = d.iloc[-1]
    atr = None
    if len(w) > 15:
        pc = w["Close"].shift(1)
        tr = (w["High"] - w["Low"]).combine((w["High"] - pc).abs(), max).combine((w["Low"] - pc).abs(), max)
        atr = float(tr.tail(14).mean())
    return {
        "date": d.index[-1].date().isoformat(),
        "close": round(float(last["Close"]), 4),
        "low": round(float(last["Low"]), 4),
        "high": round(float(last["High"]), 4),
        "weekly_atr": round(atr, 4) if atr else None,
        "fetched_at": datetime.now(TZ).isoformat(timespec="seconds"),
    }


def refresh(path: Path = PATH, quiet: bool = False) -> dict:
    d = load(path)
    for p in d["positions"]:
        if p.get("status", "open") != "open":
            continue
        try:
            p["market"] = fetch_market(p["ticker"])
        except Exception as e:  # keep previous market block
            if not quiet:
                print(f"  [positions] {p['ticker']}: refresh failed: {e}")
    save(d, path)
    return d


def metrics(p: dict) -> dict:
    m = p.get("market") or {}
    c, e, s, t = m.get("close"), p["entry_price"], p.get("stop"), p.get("target")
    atr = m.get("weekly_atr")
    out = {"close": c, "date": m.get("date"), "low": m.get("low"), "high": m.get("high"), "weekly_atr": atr}
    if c is None:
        return out
    out["pl_usd"] = round((c - e) * p["qty"], 2)
    out["pl_pct"] = round((c / e - 1) * 100, 2)
    if s is not None and e != s:
        out["r_mult"] = round((c - e) / (e - s), 2)
        out["to_stop_pct"] = round((c / s - 1) * 100, 2)
        out["to_stop_atr"] = round((c - s) / atr, 2) if atr else None
        low = m.get("low", c)
        out["stop_hit"] = low <= s
        out["near_stop"] = bool(atr) and (low - s) <= NEAR_ATR * atr
    if t is not None:
        out["to_target_pct"] = round((t / c - 1) * 100, 2)
        out["to_target_atr"] = round((t - c) / atr, 2) if atr else None
        high = m.get("high", c)
        out["target_hit"] = high >= t
        out["near_target"] = bool(atr) and (t - high) <= NEAR_ATR * atr
    return out


def cmd_check(a) -> int:
    d = load() if a.no_refresh else refresh(quiet=a.json)
    res, flagged = [], False
    for p in d["positions"]:
        if p.get("status", "open") != "open":
            continue
        m = metrics(p)
        flags = [k for k in ("stop_hit", "near_stop", "target_hit", "near_target") if m.get(k)]
        if "stop_hit" in flags: flags.remove("near_stop") if "near_stop" in flags else None
        if "target_hit" in flags: flags.remove("near_target") if "near_target" in flags else None
        flagged |= bool(flags)
        res.append({"ticker": p["ticker"], "entry": p["entry_price"], "stop": p.get("stop"), "target": p.get("target"), **m, "flags": flags})
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        if not res:
            print("no open positions")
        for r in res:
            print(f"{r['ticker']} {r.get('date')}: close {r.get('close')} (L {r.get('low')} / H {r.get('high')}), entry {r['entry']}, "
                  f"stop {r['stop']} ({r.get('to_stop_pct')}%, {r.get('to_stop_atr')} wATR), target {r['target']} "
                  f"({r.get('to_target_pct')}%, {r.get('to_target_atr')} wATR), P/L ${r.get('pl_usd')} ({r.get('pl_pct')}%), "
                  f"R {r.get('r_mult')}, wATR {r.get('weekly_atr')} -> {', '.join(r['flags']).upper() or 'OK'}")
    return 2 if flagged else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list")
    a = sp.add_parser("add")
    a.add_argument("ticker"); a.add_argument("--qty", type=float, required=True); a.add_argument("--entry", type=float, required=True)
    a.add_argument("--stop", type=float); a.add_argument("--target", type=float); a.add_argument("--date", default=date.today().isoformat())
    a.add_argument("--exchange", default=""); a.add_argument("--note", default="")
    s = sp.add_parser("set")
    s.add_argument("ticker"); s.add_argument("--stop", type=float); s.add_argument("--target", type=float); s.add_argument("--note")
    c = sp.add_parser("close")
    c.add_argument("ticker"); c.add_argument("--price", type=float, required=True); c.add_argument("--date", default=date.today().isoformat())
    sp.add_parser("refresh")
    k = sp.add_parser("check"); k.add_argument("--no-refresh", action="store_true"); k.add_argument("--json", action="store_true")
    a_ = ap.parse_args()
    if a_.cmd == "check":
        sys.exit(cmd_check(a_))
    if a_.cmd == "refresh":
        refresh(); print(f"refreshed {PATH}"); return
    d = load()
    if a_.cmd == "list":
        for p in d["positions"]:
            m = metrics(p)
            print(f"{p['ticker']:6} {p.get('status','open'):6} {p['entry_date']} qty {p['qty']} @ {p['entry_price']} stop {p.get('stop')} "
                  f"target {p.get('target')} close {m.get('close')} P/L ${m.get('pl_usd')} R {m.get('r_mult')}")
        return
    if a_.cmd == "add":
        d["positions"].append({"ticker": a_.ticker.upper(), "exchange": a_.exchange, "side": "long", "entry_date": a_.date,
                               "qty": a_.qty, "entry_price": a_.entry, "stop": a_.stop, "target": a_.target,
                               "status": "open", "note": a_.note})
    elif a_.cmd == "set":
        p = find_open(d, a_.ticker)
        for k_ in ("stop", "target", "note"):
            if getattr(a_, k_) is not None:
                p[k_] = getattr(a_, k_)
    elif a_.cmd == "close":
        p = find_open(d, a_.ticker)
        p.update(status="closed", exit_price=a_.price, exit_date=a_.date,
                 realized_pl=round((a_.price - p["entry_price"]) * p["qty"], 2))
    save(d)
    print(f"saved {PATH}")


if __name__ == "__main__":
    main()
