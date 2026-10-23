"""Bot drawings for app candidates that need one (policy 2026-10-23: bot drawings are approved by default).

Rules = v3d (fitted on Eyal's 54 TradingView drawings, /workspace/drawing-learn/infer_v3d.py, params frozen below):
  zone  = clearest valid weekly level below price: RETEST of a broken pivot high (body top -> wick high) or
          BACK-TO-SUPPORT pivot low (wick low -> body bottom), clarity >= 3, body pivot, wick edge capped at 0.5 ATR;
          a level is broken (skipped) if ANY price traded below its SL since the pivot (grace 3 weeks for closes);
          among valid levels pick the one nearest the pullback low / price / 38.2% retracement;
  entry = zone top - 0.13 ATR;  SL = entry - 1 weekly Wilder ATR, unless the lowest pullback / near-zone wick low
          (last 52 weeks, within 0.75 ATR below the zone) gives risk 0.9-1.2 ATR -> just under that wick;
  TP    = highest weekly body top of the last 26 weeks - 0.09 ATR.
Long Position is time-anchored: t_start = the week right after the last candle, t_end = +20 weekly bars.
Each row carries meta = {rule_version, why{...}} so feedback can be analyzed later.

Candidates: f_dollar_vol AND f_history AND f_no_earnings_14d AND f_technical, no live user/tv drawing, no active
'not interesting' mark, not one of his lines-only charts (tv_source user-lines), no 'structure' feedback in the last 8 weeks, and no live bot drawing (unless it is broken:
any price since it was drawn below its SL -> obsolete + redraw). A bot drawing rejected via feedback under the current
RULE_VERSION is not redrawn until the rule version changes.

    # 1) read state through the Supabase connector (execute_sql), save the JSON outputs:
    python -m srs_app.bot_drawings --print-read-sql
    # 2) compute + emit SQL (run the printed statements with execute_sql):
    python -m srs_app.bot_drawings --drawings-json D.json --labels-json L.json --feedback-json F.json --emit-sql
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

RULE_VERSION = "v3d-2026-10-23"
LEARN_DIR = Path(os.environ.get("SRS_DRAWING_LEARN", "/workspace/drawing-learn"))
REPORT = Path(__file__).resolve().parent.parent / "historical-reports" / "latest.csv"
LONG_W_BARS = 20
STRUCTURE_EXCLUDE_WEEKS = 8
# v3d parameters (fit on all 54 of his drawings, bot_drawings.json 'fit'; frozen so runs are reproducible)
FIT = dict(grace=3, wick_n=1, body_piv=2, s_min=3, wick_cap=0.5, L=52, X=0.75, lo=0.9, hi=1.2, mode="fit")

SQL_READ = {
    "drawings": "select id, ticker, kind, zone_top, zone_bottom, entry, stop, target, t_start, t_end, source, status, "
                "meta, created_at, updated_at from public.drawings where status in ('active','approved','review','rejected') "
                "order by ticker, kind;",
    "labels": "select distinct on (ticker, label) ticker, label, value, asof, until from public.labels "
              "where label = 'not_interesting' order by ticker, label, asof desc, created_at desc;",
    "feedback": "select ticker, category, created_at, rule_version from public.drawing_feedback order by created_at;",
}

_R: Dict[str, Any] = {}


def _rules():
    """Lazy import of the v3d research modules (they load hist_cache.pkl on import)."""
    if not _R:
        for p in (str(LEARN_DIR), "/workspace"):
            if p not in sys.path:
                sys.path.insert(0, p)
        import infer as V1  # noqa
        import infer_v3 as V3  # noqa
        import infer_v3d as V3D  # noqa
        _R.update(V1=V1, V3=V3, V3D=V3D,
                  P={**V3.DEFAULT, **V3D.FIXED, **FIT, "long_wick": 99, "close_n": 99})
    return _R


def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "yes", "1")


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute(ticker: str, read_date: Optional[str] = None) -> Dict[str, Any]:
    """Zone + Long Position for one ticker (v3d). has_level False -> reason, no levels."""
    R = _rules()
    V1, V3, V3D, P = R["V1"], R["V3"], R["V3D"], R["P"]
    import numpy as np
    t = ticker.upper()
    if t not in V1.H or V1.H[t] is None or V1.H[t].empty:
        return dict(ticker=t, has_level=False, reason="no price history in the scanner cache")
    rd = read_date or str(V1.H[t].index.max().date())
    C = V1.ctx(t, rd)
    A, Aw, last = C["atr"], C["atr_w"], C["c"][-1]
    out: Dict[str, Any] = dict(ticker=t, data_date=rd, price=round(float(last), 2), rule_version=RULE_VERSION)
    dly = V1.H[t]["Close"].tail(130)
    jump = float((dly / dly.shift() - 1).abs().max())
    if jump > 0.4:
        return dict(out, has_level=False, reason=f"data issue: {jump:.0%} one-day jump in 26 weeks (split?)")
    zones = V3D.valid_levels_d(t, rd, P)
    zones = [z for z in zones if not (z["lows_rel"] and min(z["lows_rel"]) < (z["sl"] - z["zb"]) / A)]
    if not zones:
        return dict(out, has_level=False, reason="no valid level: every clear retest/support below price is broken or none exists")
    # (v3d keeps zones the price dipped under within the grace weeks: a retest in progress, as in his drawings)
    lo52 = V1.fib_anchor_low(C, 52)
    fib382 = C["rh"] - 0.382 * (C["rh"] - lo52)
    ch = min(zones, key=lambda z: 0.5 * V1.zdist(C["pb_low"], z["zb"] - 0.3 * A, z["zt"] + 0.3 * A) / A
             + 0.6 * V1.zdist(last, z["zb"], z["zt"]) / A + 0.3 * abs((z["zb"] + z["zt"]) / 2 - fib382) / A)
    zb, zt = float(ch["zb"]), float(ch["zt"])
    en = zt - V3.ENTRY_BELOW_TOP * A
    sl = float(ch["sl"])
    tp = float(C["bt26"] + V3.TP_OFF * A)
    w, i = C["w"], ch["i"]
    piv = str(w.index[i].date())
    bo = ""
    if ch["kind"] == "retest":
        b = np.where(C["c"][i + 1:] > zt)[0]
        bo = str(w.index[i + 1 + int(b[0])].date()) if len(b) else ""
    last_week = _monday(datetime.strptime(rd, "%Y-%m-%d").date())
    t_start = last_week + timedelta(days=7)
    why = {
        "rule": "v3d", "branch": ch["kind"], "pivot_date": piv, "breakout_date": bo or None,
        "clarity": int(ch["strength"]), "wick_confirmations": int(ch.get("conf", 0)),
        "sl_src": ch["sl_src"], "sl_wick_low": round(sl, 2) if ch["sl_src"] == "wick_low" else None,
        "atr": round(A, 4), "atr_w": round(Aw, 4), "risk_atr_w": round((en - sl) / Aw, 2),
        "pullback_low": round(C["pb_low"], 2), "recent_high": round(C["rh"], 2), "fib382": round(fib382, 2),
        "n_valid_levels": len(zones), "price_below_zone": bool(last < zb), "dist_price_to_zone_top_atr": round((last - zt) / A, 2),
        "entry_rule": "zone_top - 0.13 ATR", "tp_rule": "max 26w body top - 0.09 ATR", "data_date": rd,
    }
    return dict(out, has_level=True, zone_top=round(zt, 2), zone_bottom=round(zb, 2), entry=round(en, 2),
                stop=round(sl, 2), target=round(tp, 2), rr=round((tp - en) / (en - sl), 2) if en > sl else None,
                zone_t_start=piv, t_start=t_start.isoformat(),
                t_end=(t_start + timedelta(days=7 * LONG_W_BARS)).isoformat(), why=why)


# ---------------- candidate selection ----------------
def _meta(r: Dict[str, Any]) -> Dict[str, Any]:
    m = r.get("meta")
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            m = None
    return m if isinstance(m, dict) else {}


def ni_active(labels: Iterable[Dict[str, Any]], today: str) -> set:
    return {str(l["ticker"]).upper() for l in labels if l.get("label", "not_interesting") == "not_interesting"
            and str(l.get("value")).lower() == "yes" and (not l.get("until") or str(l["until"])[:10] >= today)}


def low_since(ticker: str, since: str) -> Optional[float]:
    V1 = _rules()["V1"]
    d = V1.H.get(ticker)
    if d is None or d.empty:
        return None
    d = d[d.index >= since]
    return float(d["Low"].min()) if len(d) else None


def plan(report_rows: Iterable[Dict[str, Any]], drawings: Iterable[Dict[str, Any]], labels: Iterable[Dict[str, Any]],
         feedback: Iterable[Dict[str, Any]], today: Optional[str] = None, low_fn=low_since) -> Dict[str, Any]:
    """Which tickers to draw / redraw. Returns {draw: [t], obsolete: {t: [ids]}, skip: {t: reason}}."""
    today = today or date.today().isoformat()
    ni = ni_active(labels, today)
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(weeks=STRUCTURE_EXCLUDE_WEEKS)).isoformat()
    structure = {str(f["ticker"]).upper() for f in feedback
                 if f.get("category") == "structure" and str(f.get("created_at") or "") >= cutoff}
    by_t: Dict[str, List[Dict[str, Any]]] = {}
    for d in drawings:
        by_t.setdefault(str(d["ticker"]).upper(), []).append(d)
    draw, obsolete, skip = [], {}, {}
    for r in report_rows:
        t = str(r["ticker"]).upper()
        if not all(_truthy(r.get(c)) for c in ("f_dollar_vol", "f_history", "f_no_earnings_14d", "f_technical")):
            continue
        if str(r.get("tv_source") or "") == "user-lines":
            skip[t] = "his own Fib / horizontal lines (user-lines)"; continue
        rows = by_t.get(t, [])
        live = [d for d in rows if d.get("status") in ("active", "approved", "review")]
        if any(d.get("source") in ("user", "tv") for d in live):
            continue  # his drawing (or an imported TV one) - never touched
        if t in ni:
            skip[t] = "not interesting"; continue
        if t in structure:
            skip[t] = f"structure feedback < {STRUCTURE_EXCLUDE_WEEKS}w"; continue
        bots = [d for d in live if d.get("source") == "bot"]
        if bots:
            stops = [float(d["stop"]) for d in bots if d.get("kind") == "long" and d.get("stop") is not None]
            since = min(str(d.get("created_at") or today)[:10] for d in bots)
            lo = low_fn(t, since) if stops else None
            if stops and lo is not None and lo < min(stops):
                obsolete[t] = [d["id"] for d in bots]
                draw.append(t)
            else:
                skip[t] = "live bot drawing"
            continue
        rej = [d for d in rows if d.get("source") == "bot" and d.get("status") == "rejected"]
        if any(_meta(d).get("rule_version") == RULE_VERSION for d in rej):
            skip[t] = "rejected under the current rule version"; continue
        draw.append(t)
    return {"draw": draw, "obsolete": obsolete, "skip": skip}


def emit_sql(results: List[Dict[str, Any]], obsolete: Dict[str, List[str]]) -> List[str]:
    from srs_app.sync import sql_insert_bot_drawing, sql_mark_obsolete
    out = []
    for ids in obsolete.values():
        out += [sql_mark_obsolete(i) for i in ids]
    for r in results:
        if not r.get("has_level"):
            continue
        meta = {"rule_version": RULE_VERSION, "why": r["why"]}
        note = f"BOT {RULE_VERSION}: {r['why']['branch']} {r['why']['pivot_date']}, SL {r['why']['sl_src']}"
        out.append(sql_insert_bot_drawing(r["ticker"], "zone", zone_top=r["zone_top"], zone_bottom=r["zone_bottom"],
                                          t_start=r["zone_t_start"], note=note, meta=meta))
        out.append(sql_insert_bot_drawing(r["ticker"], "long", entry=r["entry"], stop=r["stop"], target=r["target"],
                                          t_start=r["t_start"], t_end=r["t_end"], note=note, meta=meta))
    return out


def _load_rows(p: Optional[str]) -> List[Dict[str, Any]]:
    if not p:
        return []
    from srs_app.app_drawings import load_rows  # tolerant of raw connector output
    return load_rows(Path(p))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--print-read-sql", action="store_true")
    ap.add_argument("--report", default=str(REPORT))
    ap.add_argument("--drawings-json"); ap.add_argument("--labels-json"); ap.add_argument("--feedback-json")
    ap.add_argument("--tickers", help="comma list: compute only these (ignores selection)")
    ap.add_argument("--emit-sql", action="store_true")
    ap.add_argument("--out", help="also write the plan + results JSON here")
    a = ap.parse_args()
    if a.print_read_sql:
        for k, v in SQL_READ.items():
            print(f"-- {k}\n{v}")
        return
    import pandas as pd
    if a.tickers:
        pl = {"draw": [t.strip().upper() for t in a.tickers.split(",") if t.strip()], "obsolete": {}, "skip": {}}
    else:
        rows = pd.read_csv(a.report).to_dict("records")
        pl = plan(rows, _load_rows(a.drawings_json), _load_rows(a.labels_json), _load_rows(a.feedback_json))
    res = [compute(t) for t in pl["draw"]]
    if a.out:
        Path(a.out).write_text(json.dumps({"plan": pl, "results": res}, indent=1, default=str))
    if a.emit_sql:
        print("\n".join(emit_sql(res, pl["obsolete"])))
    else:
        for r in res:
            print(r["ticker"], "LEVEL" if r.get("has_level") else "none", {k: r.get(k) for k in
                  ("zone_bottom", "zone_top", "entry", "stop", "target", "rr")} if r.get("has_level") else r.get("reason"))
        print("skip:", pl["skip"])


if __name__ == "__main__":
    main()
