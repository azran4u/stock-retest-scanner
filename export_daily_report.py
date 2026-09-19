#!/usr/bin/env python3
"""Export a full-universe daily screen report CSV for historical-reports/ + Pages.

Usage:
  python export_daily_report.py \\
    --results /workspace/stock_screen_results.csv \\
    --verify /workspace/stock_screen_verify.csv \\
    --date 2026-09-18 \\
    --out-dir /path/to/repo/historical-reports \\
    [--handoff /workspace/stock-screener/handoff_YYYY-MM-DD.json]

Writes:
  historical-reports/YYYY-MM-DD.csv
  historical-reports/latest.csv
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

REPORT_COLS = [
    "ticker",
    "status",
    "current_price",
    "entry",
    "sl",
    "tp",
    "rr",
    "zone_lo",
    "zone_hi",
    "atr",
    "short_float_pct",
    "inst_own_pct",
    "dollar_vol_30d",
    "avg_vol_30d",
    "weekly_bars",
    "days_to_earnings",
    "earnings_known",
    "earnings_blackout",
    "tradingview_url",
    "finviz_url",
    "reason",
]


def _pct(val: Any) -> Optional[float]:
    if val is None or (isinstance(val, float) and not np.isfinite(val)) or pd.isna(val):
        return None
    f = float(val)
    # FinViz / yfinance often store 0.041 for 4.1%
    if f <= 1.5:
        return round(f * 100, 2)
    return round(f, 2)


def _load_exchange_map(verify: pd.DataFrame, grok_path: Optional[Path]) -> Dict[str, str]:
    ex_map: Dict[str, str] = {}
    if "tradingview_url" in verify.columns:
        for url in verify["tradingview_url"].dropna():
            m = re.search(r"symbol=([A-Z]+):([A-Z0-9.]+)", str(url))
            if m:
                ex, sym = m.group(1), m.group(2)
                ex_map[sym] = ex
                ex_map[sym.replace(".", "-")] = ex
                ex_map[sym.replace("-", ".")] = ex
    if grok_path and grok_path.exists():
        for line in grok_path.read_text().splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            ex, sym = line.split(":", 1)
            ex, sym = ex.strip().upper(), sym.strip().upper()
            if ex and sym:
                ex_map[sym] = ex
                ex_map[sym.replace(".", "-")] = ex
                ex_map[sym.replace("-", ".")] = ex
    return ex_map


def tv_url(ticker: str, ex_map: Dict[str, str]) -> str:
    raw = str(ticker).strip().upper()
    tv_ticker = raw.replace("-", ".")
    ex = ex_map.get(raw) or ex_map.get(tv_ticker) or "NASDAQ"
    return f"https://www.tradingview.com/chart/?symbol={ex}:{tv_ticker}"


def _as_bool(val: Any, default: bool = False) -> bool:
    if val is None or (isinstance(val, float) and not np.isfinite(val)) or pd.isna(val):
        return default
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return bool(val)


def build_report(
    results: pd.DataFrame,
    verify: Optional[pd.DataFrame] = None,
    handoff: Optional[Dict[str, Any]] = None,
    grok_path: Optional[Path] = None,
) -> pd.DataFrame:
    verify = verify if verify is not None else pd.DataFrame()
    ex_map = _load_exchange_map(verify, grok_path)
    v_idx = verify.set_index("ticker") if len(verify) and "ticker" in verify.columns else None

    earnings_skips = set((handoff or {}).get("earnings_skips") or [])
    pass_earn: Dict[str, Dict[str, Any]] = {}
    for p in ((handoff or {}).get("all_passes") or []) + ((handoff or {}).get("new_passes") or []):
        t = p.get("ticker")
        if t:
            pass_earn[t] = p

    rows = []
    for _, r in results.iterrows():
        t = r["ticker"]
        row: Dict[str, Any] = {c: None for c in REPORT_COLS}
        row["ticker"] = t
        row["status"] = r.get("status")
        row["reason"] = r.get("reason", "")

        if v_idx is not None and t in v_idx.index:
            v = v_idx.loc[t]
            if isinstance(v, pd.DataFrame):
                v = v.iloc[0]
            for c in REPORT_COLS:
                if c == "ticker" or c not in v.index:
                    continue
                val = v[c]
                if pd.isna(val):
                    continue
                row[c] = val
            row["status"] = r.get("status")
            if pd.notna(v.get("reason")) and str(v.get("reason")):
                row["reason"] = v["reason"]
        else:
            price = r.get("price", r.get("current_price"))
            row["current_price"] = None if pd.isna(price) else price
            for c in (
                "entry",
                "sl",
                "tp",
                "rr",
                "zone_lo",
                "zone_hi",
                "atr",
                "dollar_vol_30d",
                "avg_vol_30d",
                "weekly_bars",
            ):
                val = r.get(c)
                row[c] = None if (val is None or (isinstance(val, float) and pd.isna(val))) else val
            if row["dollar_vol_30d"] is None and not pd.isna(r.get("dollar_vol")):
                row["dollar_vol_30d"] = r.get("dollar_vol")
            row["short_float_pct"] = _pct(r.get("short_float") if "short_float" in r.index else r.get("short_float_pct"))
            row["inst_own_pct"] = _pct(r.get("inst_own") if "inst_own" in r.index else r.get("inst_own_pct"))
            row["earnings_known"] = False
            row["earnings_blackout"] = False
            row["finviz_url"] = f"https://finviz.com/quote.ashx?t={ticker}"
        row["tradingview_url"] = tv_url(t, ex_map)

        if t in pass_earn:
            pe = pass_earn[t]
            if row.get("days_to_earnings") is None and pe.get("days_to_earnings") is not None:
                row["days_to_earnings"] = pe["days_to_earnings"]
                row["earnings_known"] = pe.get("earnings_known", True)
            if pe.get("tradingview_url"):
                row["tradingview_url"] = pe["tradingview_url"]
            if pe.get("short_float_pct") is not None and row.get("short_float_pct") is None:
                row["short_float_pct"] = pe["short_float_pct"]

        if t in earnings_skips:
            row["earnings_blackout"] = True
            row["earnings_known"] = True if row.get("earnings_known") is None else row["earnings_known"]
            reason = str(row.get("reason") or "")
            if "earnings blackout" not in reason.lower():
                row["reason"] = (reason + " | earnings blackout (<14d)").strip(" |")

        if not row.get("tradingview_url"):
            row["tradingview_url"] = tv_url(t, ex_map)

        row["earnings_known"] = _as_bool(row.get("earnings_known"), False)
        row["earnings_blackout"] = _as_bool(row.get("earnings_blackout"), False)
        rows.append(row)

    df = pd.DataFrame(rows)[REPORT_COLS]

    def sort_key(i: int):
        status_rank = 0 if df.at[i, "status"] == "PASS" else 1
        rr = df.at[i, "rr"]
        try:
            rr_val = -float(rr) if pd.notna(rr) else 999.0
        except Exception:
            rr_val = 999.0
        return (status_rank, rr_val, df.at[i, "ticker"])

    order = sorted(range(len(df)), key=sort_key)
    return df.iloc[order].reset_index(drop=True)


def write_reports(df: pd.DataFrame, out_dir: Path, report_date: str) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dated = out_dir / f"{report_date}.csv"
    latest = out_dir / "latest.csv"
    df.to_csv(dated, index=False)
    df.to_csv(latest, index=False)
    return {"dated": dated, "latest": latest}


def update_manifest(repo_root: Path, report_date: str, filename: str, out_dir: Path) -> Path:
    """Write reports.json next to index.html. CSVs live only in historical-reports/ (Pages source=/)."""
    repo_root.mkdir(parents=True, exist_ok=True)
    manifest_path = repo_root / "reports.json"
    found = []
    for p in sorted(out_dir.glob("????-??-??.csv"), reverse=True):
        found.append(
            {
                "date": p.stem,
                "file": p.name,
                "path": f"historical-reports/{p.name}",
            }
        )
    if not any(e["date"] == report_date for e in found):
        found.insert(
            0,
            {
                "date": report_date,
                "file": filename,
                "path": f"historical-reports/{filename}",
            },
        )
        found.sort(key=lambda e: e.get("date", ""), reverse=True)
    manifest_path.write_text(json.dumps(found, indent=2) + "\n")
    return manifest_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path, default=Path("/workspace/stock_screen_results.csv"))
    ap.add_argument("--verify", type=Path, default=Path("/workspace/stock_screen_verify.csv"))
    ap.add_argument("--handoff", type=Path, default=None)
    ap.add_argument("--grok", type=Path, default=Path("/workspace/Grok.txt"))
    ap.add_argument("--date", required=True, help="Report date YYYY-MM-DD")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/workspace/stock-screener/historical-reports"),
    )
    ap.add_argument(
        "--docs-dir",
        type=Path,
        default=None,
        help="If set, also refresh docs/reports.json",
    )
    args = ap.parse_args()

    results = pd.read_csv(args.results)
    verify = pd.read_csv(args.verify) if args.verify and args.verify.exists() else pd.DataFrame()
    handoff = None
    if args.handoff and args.handoff.exists():
        handoff = json.loads(args.handoff.read_text())
    else:
        # auto-discover handoff for date
        guess = Path(f"/workspace/stock-screener/handoff_{args.date}.json")
        if guess.exists():
            handoff = json.loads(guess.read_text())

    df = build_report(results, verify, handoff, args.grok if args.grok.exists() else None)
    paths = write_reports(df, args.out_dir, args.date)

    n_pass = int((df["status"] == "PASS").sum())
    n_fail = int((df["status"] == "FAIL").sum())
    n_bo = int(df["earnings_blackout"].astype(bool).sum())
    print(
        f"Report {args.date}: {len(df)} rows "
        f"(PASS={n_pass}, FAIL={n_fail}, earnings_blackout={n_bo})"
    )
    print(f"  {paths['dated']}")
    print(f"  {paths['latest']}")

    docs_dir = args.docs_dir
    if docs_dir is None:
        # sibling docs/ next to historical-reports
        sibling = args.out_dir.parent / "docs"
        if sibling.is_dir() or (args.out_dir.parent / "README.md").exists():
            docs_dir = sibling
    if docs_dir is not None:
        mp = update_manifest(docs_dir, args.date, f"{args.date}.csv", args.out_dir)
        print(f"  manifest {mp}")


if __name__ == "__main__":
    main()
