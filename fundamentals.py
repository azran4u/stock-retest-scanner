#!/usr/bin/env python3
"""Fundamentals analysis for graded tickers (A/B/C/D) -> analysis/analysis.json (shown on the dashboard).

The analysis text needs web research (news, guidance, pros/cons), so this is NOT part of the
nightly routine. The script handles the mechanical parts:

  python fundamentals.py status                 # graded tickers in the latest report + which lack analysis / are stale (>14d)
  python fundamentals.py todo                   # just the tickers that need (re)analysis, space-separated
  python fundamentals.py scaffold T [T ...]     # write analysis/drafts/T.json: Yahoo key stats + empty fields to research
  python fundamentals.py merge analysis/drafts/T.json [...]   # validate, fill {placeholders} from the stats, upsert into analysis.json
  python fundamentals.py validate               # check analysis.json

Grading mirrors filters.js applyLive with the DEFAULT parameters (E=14, V=$50M, N=5, X=3) and default
position sizing (account $5000, risk 1%, position 15%). --include-untradable also lists tickers that pass
every must-have except "tradable with account" (they get a grade with a larger account).

Draft format (one ticker): {"ticker","name","business","news":[{"date","title","url","source"}],
"pros":[...2-4],"cons":[...2-4],"take": "...", "sources":[{"label","url"}]}. Text may use {fpe} {tpe} {ps}
{om} {pm} {rg} {roe} {de} {div} {cash} {debt} {fcf} {tgt} {rec} {lo} {hi} {src}, filled from Yahoo Finance
key statistics (yfinance) at merge time. Never invent figures: cite a source for every number.
"""
import argparse, datetime as dt, json, math, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ANALYSIS = ROOT / "analysis" / "analysis.json"
DRAFTS = ROOT / "analysis" / "drafts"
STALE_DAYS = 14
DEFAULTS = dict(earn_days=14, min_dollar_vol=50e6, smooth_n=5, rr_x=3.0, account=5000.0, risk_pct=1.0, pos_pct=15.0)
EVIDENCE = ["f_weekly_reversal", "f_daily_reversal", "ev_first_reaction", "ev_double_bottom",
            "f_smooth_streak", "f_rr_x", "ev_ma_support", "ev_fib"]
METRIC_KEYS = ["sector", "industry", "longName", "trailingPE", "forwardPE", "priceToSalesTrailing12Months", "profitMargins",
               "operatingMargins", "revenueGrowth", "returnOnEquity", "debtToEquity", "dividendYield", "totalCash",
               "totalDebt", "freeCashflow", "targetMeanPrice", "recommendationKey", "fiftyTwoWeekLow",
               "fiftyTwoWeekHigh", "currentPrice", "marketCap"]


def today():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()  # Asia/Jerusalem (box clock)


def latest_report():
    reps = json.loads((ROOT / "reports.json").read_text())
    return ROOT / reps[0]["path"], reps[0]["date"]


def t(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def fnum(v):
    try:
        x = float(v)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def grade_rows(path, include_untradable=False, P=DEFAULTS):
    """Python mirror of filters.js applyLive (default params + default sizing)."""
    import csv
    rows = list(csv.DictReader(open(path, newline="")))
    td = today()
    out = []
    for r in rows:
        if "ev_fib" not in r:
            continue
        ed = (r.get("earnings_date") or "")[:10]
        try:
            days = (dt.date.fromisoformat(ed) - td).days
        except ValueError:
            days = None
        entry, sl = fnum(r.get("tv_entry")), fnum(r.get("tv_sl"))
        shares = 0
        if r.get("tv_found") == "yes" and entry and sl is not None and entry > sl:
            shares = math.floor(min(P["account"] * P["risk_pct"] / 100 / (entry - sl), P["account"] * P["pos_pct"] / 100 / entry) + 1e-9)
        must = {
            "short float": t(r.get("f_short_float")),
            "earnings": days is not None and days >= P["earn_days"],
            "$vol": (fnum(r.get("dollar_vol_30d")) or 0) >= P["min_dollar_vol"],
            "history": t(r.get("f_history")),
            "technical": t(r.get("f_technical")),
            "near zone": t(r.get("f_near_zone")),
            "TV R:R>=2": t(r.get("f_rr")),
            "tradable": shares >= 1,
        }
        failed = [k for k, ok in must.items() if not ok]
        if failed and not (include_untradable and failed == ["tradable"]):
            continue
        ev = dict(r)
        ev["f_smooth_streak"] = str((fnum(r.get("smooth_streak_weeks")) or 0) >= P["smooth_n"])
        ev["f_rr_x"] = str(t(r.get("f_rr")) and (fnum(r.get("tv_rr")) or 0) >= P["rr_x"])
        missing = [c for c in EVIDENCE if not t(ev.get(c))]
        g = "ABC"[len(missing)] if len(missing) < 3 else "D"
        out.append(dict(ticker=r["ticker"], grade=g, tv_rr=fnum(r.get("tv_rr")), untradable=bool(failed)))
    return sorted(out, key=lambda x: (x["grade"], -(x["tv_rr"] or 0)))


def load_analysis():
    if ANALYSIS.exists():
        return json.loads(ANALYSIS.read_text())
    return {"schema": 1, "generated_at": None, "tickers": {}}


def save_analysis(a):
    dates = [v.get("generated_at") for v in a["tickers"].values() if v.get("generated_at")]
    a["generated_at"] = max(dates) if dates else None
    a["tickers"] = dict(sorted(a["tickers"].items()))
    ANALYSIS.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS.write_text(json.dumps(a, indent=1, ensure_ascii=False) + "\n")


def needs_work(a, graded):
    td = today()
    todo = []
    for g in graded:
        e = a["tickers"].get(g["ticker"])
        if not e:
            todo.append((g, "missing"))
            continue
        age = (td - dt.date.fromisoformat(e["generated_at"])).days
        if age > STALE_DAYS:
            todo.append((g, f"stale ({age}d)"))
    return todo


def yahoo_symbol(tk):
    return tk.replace(".", "-")


def fetch_metrics(tk):
    import yfinance as yf
    info = yf.Ticker(yahoo_symbol(tk)).info or {}
    m = {k: info.get(k) for k in METRIC_KEYS}
    m["as_of"] = today().isoformat()
    m["source"] = f"https://finance.yahoo.com/quote/{yahoo_symbol(tk)}/key-statistics"
    return m


def fmt_metrics(m):
    """Placeholder values for draft text; missing numbers become 'n/a' (and validate warns)."""
    def pct(k):
        v = m.get(k); return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else "n/a"
    def x(k, d=1):
        v = m.get(k); return f"{v:.{d}f}" if isinstance(v, (int, float)) else "n/a"
    def bn(k):
        v = m.get(k)
        if not isinstance(v, (int, float)):
            return "n/a"
        return f"${v / 1e9:.2f}B" if abs(v) >= 1e9 else f"${v / 1e6:.0f}M"
    dy = m.get("dividendYield")
    return dict(fpe=x("forwardPE"), tpe=x("trailingPE"), ps=x("priceToSalesTrailing12Months"), om=pct("operatingMargins"),
                pm=pct("profitMargins"), rg=pct("revenueGrowth"), roe=pct("returnOnEquity"), de=x("debtToEquity", 0),
                div=(f"{dy:.1f}%" if isinstance(dy, (int, float)) else "n/a"),  # yfinance reports this one already in %
                cash=bn("totalCash"), debt=bn("totalDebt"), fcf=bn("freeCashflow"), tgt=x("targetMeanPrice", 0),
                rec=str(m.get("recommendationKey") or "n/a").replace("_", " "), lo=x("fiftyTwoWeekLow", 2),
                hi=x("fiftyTwoWeekHigh", 2), src="Yahoo")


def fill(obj, vals):
    if isinstance(obj, str):
        return obj.format(**vals)
    if isinstance(obj, list):
        return [fill(o, vals) for o in obj]
    if isinstance(obj, dict):
        return {k: fill(v, vals) if k in ("business", "pros", "cons", "take", "title") else v for k, v in obj.items()}
    return obj


def validate_entry(tk, e):
    errs = []
    for k in ("name", "sector", "industry", "business", "news", "pros", "cons", "take", "generated_at"):
        if not e.get(k):
            errs.append(f"{tk}: missing {k}")
    for n in e.get("news", []):
        if not (n.get("date") and n.get("url", "").startswith("http") and n.get("title")):
            errs.append(f"{tk}: news item needs date/title/url: {n}")
    for k in ("pros", "cons"):
        if not 2 <= len(e.get(k, [])) <= 4:
            errs.append(f"{tk}: {k} should have 2-4 bullets")
    blob = " ".join([e.get("business") or "", e.get("take") or ""] + list(e.get("pros") or []) + list(e.get("cons") or [])
                    + [n.get("title") or "" for n in e.get("news") or []])
    if "n/a" in blob:
        errs.append(f"{tk}: a placeholder resolved to n/a (Yahoo lacks that figure) — reword or drop it")
    if "{" in blob:
        errs.append(f"{tk}: unfilled placeholder")
    return errs


def cmd_status(args):
    path, date = latest_report()
    graded = grade_rows(path, args.include_untradable)
    a = load_analysis()
    todo = {g["ticker"]: why for g, why in needs_work(a, graded)}
    print(f"report {date}: {len(graded)} graded ({'incl. untradable' if args.include_untradable else 'default sizing'})")
    for g in graded:
        e = a["tickers"].get(g["ticker"])
        st = todo.get(g["ticker"]) or f"ok ({e['generated_at']})"
        print(f"  {g['grade']} {g['ticker']:<6} R:R {g['tv_rr'] or 0:.2f}{' (untradable)' if g['untradable'] else ''}  {st}")
    print(f"needs analysis: {' '.join(todo) or '-'}")


def cmd_todo(args):
    path, _ = latest_report()
    print(" ".join(g["ticker"] for g, _ in needs_work(load_analysis(), grade_rows(path, args.include_untradable))))


def cmd_scaffold(args):
    DRAFTS.mkdir(parents=True, exist_ok=True)
    for tk in args.tickers:
        m = fetch_metrics(tk)
        d = {"ticker": tk, "name": m.get("longName") or tk, "business": "", "news": [{"date": "YYYY-MM-DD", "title": "", "url": "", "source": ""}],
             "pros": [], "cons": [], "take": "", "sources": [], "_metrics_preview": fmt_metrics(m)}
        p = DRAFTS / f"{tk}.json"
        p.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {p}")


def cmd_merge(args):
    a = load_analysis()
    path, _ = latest_report()
    grades = {g["ticker"]: g["grade"] for g in grade_rows(path, include_untradable=True)}
    errs = []
    for f in args.files:
        d = json.loads(Path(f).read_text())
        tk = d["ticker"]
        m = d.get("metrics") or fetch_metrics(tk)
        vals = fmt_metrics(m)
        e = fill({k: v for k, v in d.items() if not k.startswith("_") and k not in ("ticker", "metrics")}, vals)
        e["sector"] = e.get("sector") or m.get("sector")
        e["industry"] = e.get("industry") or m.get("industry")
        e["metrics"] = {k: m.get(k) for k in ("forwardPE", "trailingPE", "operatingMargins", "revenueGrowth", "debtToEquity",
                                               "dividendYield", "targetMeanPrice", "recommendationKey", "as_of", "source")}
        e["generated_at"] = d.get("generated_at") or today().isoformat()
        e["grade_at_generation"] = grades.get(tk, "")
        srcs = list(e.get("sources") or [])
        if not any("finance.yahoo.com" in s.get("url", "") for s in srcs):
            srcs.append({"label": f"Yahoo Finance key statistics ({m.get('as_of')})", "url": m["source"]})
        for n in e.get("news", []):
            if not any(s.get("url") == n["url"] for s in srcs):
                srcs.append({"label": n.get("source") or n["url"], "url": n["url"]})
        e["sources"] = srcs
        es = validate_entry(tk, e)
        errs += es
        if es and not args.force:
            print(f"skip {tk}: " + "; ".join(es))
            continue
        a["tickers"][tk] = e
        print(f"merged {tk} ({e['grade_at_generation'] or 'ungraded'})")
    save_analysis(a)
    if errs:
        sys.exit(1 if not args.force else 0)


def cmd_validate(args):
    a = load_analysis()
    errs = [x for tk, e in a["tickers"].items() for x in validate_entry(tk, e)]
    print("\n".join(errs) or f"ok: {len(a['tickers'])} tickers, generated_at {a.get('generated_at')}")
    sys.exit(1 if errs else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for n, fn in (("status", cmd_status), ("todo", cmd_todo)):
        p = sp.add_parser(n); p.add_argument("--include-untradable", action="store_true"); p.set_defaults(fn=fn)
    p = sp.add_parser("scaffold"); p.add_argument("tickers", nargs="+"); p.set_defaults(fn=cmd_scaffold)
    p = sp.add_parser("merge"); p.add_argument("files", nargs="+"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_merge)
    p = sp.add_parser("validate"); p.set_defaults(fn=cmd_validate)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
