"""Expert watchlist (Eyal 2026-11-01): stocks whose price is near a valid v7 expert zone (broken resistance retest),
with an expert R:R >= 2, tradable, clear of earnings, ranked by the bot's readiness judgment.

Written nightly by the export to app/data/expert_watch.json (separate file, never a PASS / drawing / sizing input):
  {"generated_at", "asof", "criteria": {...constants...}, "items": [{t, tier, rank, comp, zone, score, dist, side,
   entry, sl, tp, rr, risk_pct, shares, signals: [...], reason_he}]}

Criteria (all must hold; constants below):
  1. valid v7 expert zone (expert_zones.json ok) - implies the 30-week MA is not falling (expert_zone rule 3)
  2. price inside the zone or above it by <= WATCH_MAX_DIST_ATR weekly ATR (not under the bottom)
  3. expert R:R >= WATCH_MIN_RR
  4. no earnings within EARN_DAYS days and the last completed week is not an earnings week (the export's gates
     f_no_earnings_14d / f_after_earnings_week; tickers outside the report: earnings.json)
  5. tradable: risk per share (entry - SL) <= MAX_RISK_USD, so >= 1 share at the $55 max risk; risk % <= WATCH_MAX_RISK_PCT
Readiness (the bot's judgment; tier 'מוכנה' when readiness >= READY_MIN_PTS = a weekly signal or the confirmation,
else 'ממתינה לאישור' - a daily reversal alone ranks higher inside that tier but is not enough):
  confirm  : the last completed weekly close is above the zone top and one of the last READY_WEEKS weeks traded
             into the zone (low <= top)                                                                            +3
  hammerW  : a weekly hammer (H textbook +3 / h near-hammer +2) touching the zone in the last READY_WEEKS weeks
  revW     : a weekly reversal candle (export revc: hammer / engulfing / strong close / rejection) touching it   +2
  revD     : a daily reversal candle touching it in the last READY_DAYS sessions                                 +1
  touch = low <= top + 0.5 ATR and (low >= bottom - 0.5 ATR or close >= bottom) (same gate as the app filters)
Rank: composite = 10 x readiness + 0.5 x score + 5 x min(R:R, 5) - 10 x distance (ATR), ready tier first.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from srs_app import expert_zone as E

WATCH_MAX_DIST_ATR = 1.0
WATCH_MIN_RR = 2.0
WATCH_MAX_RISK_PCT = 10.0
MAX_RISK_USD = 55.0
EARN_DAYS = 14
READY_WEEKS = 2
READY_DAYS = 10
READY_MIN_PTS = 2
REV_KINDS = ["hammer", "engulfing", "strong_close", "rejection"]     # report_filters CONFIG reversal_kinds (bit order)
REV_HE = {"hammer": "פטיש", "engulfing": "בולע", "strong_close": "סגירה חזקה", "rejection": "דחייה"}
TIER_READY, TIER_WAIT = "מוכנה", "ממתינה לאישור"


def _touch(lo: float, cl: float, top: float, bot: float, a: float) -> bool:
    return lo <= top + 0.5 * a and (lo >= bot - 0.5 * a or cl >= bot)


def _kinds(mask: int) -> List[str]:
    return [k for i, k in enumerate(REV_KINDS) if mask & (1 << i)]


def _reaction_day(d: date, t: Optional[str]) -> date:
    """Trading day the market reacts to a report: bmo / unknown -> that day, amc -> next weekday."""
    if t == "amc":
        d += timedelta(days=3 if d.weekday() == 4 else (2 if d.weekday() == 5 else 1))
    return d


def earn_block(em: Dict[str, Any], row: Dict[str, Any], asof: date, last_week: Optional[str]) -> Optional[str]:
    """Why the earnings gate blocks a ticker (None = clear). Evaluated LIVE on `asof` for every ticker (bug 2026-11-01:
    the report row's f_no_earnings_14d was trusted, but it is computed on the report date and is missing for many
    rows, so IRM / ROK (11/05) and MUFG (11/13) slipped through). Sources: earnings.json {T: {p: [{d, t}], n, nt}}
    (flat, keyed by ticker) and the row's earnings_date as a fallback.
      - next report within EARN_DAYS days (0 <= days < EARN_DAYS, same rule as the scanner's f_no_earnings_14d)
      - a report reacted to in the last completed week (Mon last_week .. Fri) or after it up to asof."""
    nxt = []
    if em.get("n"):
        nxt.append(date.fromisoformat(str(em["n"])[:10]))
    if isinstance(row.get("earnings_date"), str) and row["earnings_date"][:10]:
        try:
            nxt.append(date.fromisoformat(row["earnings_date"][:10]))
        except ValueError:
            pass
    for n in sorted(set(nxt)):
        dd = (n - asof).days
        if 0 <= dd < EARN_DAYS:
            return f"דוחות בעוד {dd} ימים ({n.isoformat()})"
    if row.get("f_no_earnings_14d") is False:                # scanner said so on the report date (conservative)
        return "דוחות בקרוב (סורק)"
    if row.get("f_after_earnings_week") is False:
        return "שבוע דוחות (סורק)"
    if last_week:
        mon = date.fromisoformat(last_week)
        past = [(date.fromisoformat(str(p["d"])[:10]), p.get("t")) for p in em.get("p", []) or [] if p.get("d")]
        if em.get("n"):
            past.append((date.fromisoformat(str(em["n"])[:10]), em.get("nt")))
        for d, t in past:
            r = _reaction_day(d, t)
            if mon <= r <= max(asof, mon + timedelta(days=4)) and d <= asof:
                return f"דוחות בשבוע האחרון ({d.isoformat()})"
    return None


def signals(z: Dict[str, Any], weeks: List[Dict[str, Any]], rv: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Readiness signals of one ticker (module doc). weeks = completed weekly bars (oldest first)."""
    top, bot, A = z["top"], z["bottom"], z["atr_w"]
    out: List[Dict[str, Any]] = []
    recent = weeks[-READY_WEEKS:]
    if recent and recent[-1]["close"] > top and any(w["low"] <= top for w in recent):
        out.append({"k": "confirm", "pts": 3, "he": "סגירה שבועית מעל האזור אחרי נגיעה", "short": "סגירה שבועית מעל האזור אחרי נגיעה"})
    for h in z.get("hammers") or []:
        if h["k"] <= READY_WEEKS:
            out.append({"k": "hammerW", "pts": 3 if h["s"] == "H" else 2, "w": h["w"],
                        "he": "פטיש שבועי על האזור" if h["s"] == "H" else "כמעט-פטיש שבועי על האזור",
                        "short": "פטיש שבועי על האזור" if h["s"] == "H" else "כמעט-פטיש שבועי על האזור"})
            break
    if rv:
        for k, mask, lo, cl, a in rv.get("w") or []:
            if k < READY_WEEKS and _touch(lo, cl, top, bot, a or A):
                ks = [x for x in _kinds(mask) if not (x == "hammer" and any(s["k"] == "hammerW" for s in out))]
                if ks:
                    out.append({"k": "revW", "pts": 2, "he": "נר היפוך שבועי על האזור (" + ", ".join(REV_HE[x] for x in ks) + ")",
                                "short": "נר היפוך שבועי על האזור"})
                    break
        for k, mask, lo, cl, a in rv.get("d") or []:
            if k < READY_DAYS and _touch(lo, cl, top, bot, a or A):
                out.append({"k": "revD", "pts": 1, "he": "נר היפוך יומי על האזור (" + ", ".join(REV_HE[x] for x in _kinds(mask)) + ")",
                                "short": "נר היפוך יומי על האזור"})
                break
    return out


def build(out: Path, rows: List[Dict[str, Any]], revc: Dict[str, Any], asof: Optional[str] = None) -> Dict[str, Any]:
    doc = json.loads((out / "expert_zones.json").read_text())
    try:
        earn = json.loads((out / "earnings.json").read_text())
    except Exception:
        earn = {}
    by = {r["ticker"]: r for r in rows}
    ad = date.fromisoformat(asof) if asof else date.today()
    items = []
    excluded: Dict[str, str] = {}
    for t, z in doc.get("tickers", {}).items():
        if not z.get("ok") or not z.get("trade"):
            continue
        try:
            r = by.get(t, {})
            cf = out / "candles" / f"{t}.json"
            daily = json.loads(cf.read_text())["d"] if cf.exists() else []
            px = r.get("current_price")
            px = float(px) if px not in (None, "") else (float(daily[-1][4]) if daily else float(z["price"]))
            top, bot, A = z["top"], z["bottom"], z["atr_w"]
            if px < bot:
                continue
            dist = 0.0 if px <= top else (px - top) / A
            if dist > WATCH_MAX_DIST_ATR:
                continue
            tr = z["trade"]
            if tr.get("rr") is None or tr["rr"] < WATCH_MIN_RR:
                continue
            risk = tr["entry"] - tr["sl"]
            if risk <= 0 or risk > MAX_RISK_USD or tr["risk_pct"] > WATCH_MAX_RISK_PCT:
                continue
            eb = earn_block(earn.get(t) or {}, r, ad, z.get("last_week"))
            if eb:
                excluded[t] = eb
                continue
            W = E.weekly(daily) if daily else []
            if W and not E.week_complete(W[-1]["last"], asof):
                W = W[:-1]
            sg = signals(z, W, revc.get(t))
            ready = sum(s["pts"] for s in sg)
            comp = 10 * ready + 0.5 * (z.get("score") or 0) + 5 * min(tr["rr"], 5) - 10 * dist
            where = "בתוך האזור" if dist == 0 else f"{dist:.1f} ATR מעל"
            best = max(sg, key=lambda s: s["pts"]) if sg else None   # strongest signal only (Eyal 2026-11-01: short line)
            reason = " · ".join([best["short"] if best else "ממתינה לסימן היפוך", f"R:R {tr['rr']:.1f}", where])
            items.append({"t": t, "tier": TIER_READY if ready >= READY_MIN_PTS else TIER_WAIT, "comp": round(comp, 1),
                          "zone": [bot, top], "score": z.get("score"), "dist": round(dist, 2),
                          "entry": tr["entry"], "sl": tr["sl"], "tp": tr["tp"], "rr": tr["rr"], "risk_pct": tr["risk_pct"],
                          "shares": int(math.floor(MAX_RISK_USD / risk)), "signals": sg, "reason_he": reason,
                          "in_report": bool(r)})
        except Exception as e:  # one ticker never breaks the list
            print(f"  [expert watch] {t}: {e}")
    items.sort(key=lambda x: (x["tier"] != TIER_READY, -x["comp"], x["t"]))
    for i, x in enumerate(items, 1):
        x["rank"] = i
    res = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "asof": asof or ad.isoformat(),
           "rule_version": doc.get("rule_version"),
           "criteria": {"max_dist_atr": WATCH_MAX_DIST_ATR, "min_rr": WATCH_MIN_RR, "max_risk_pct": WATCH_MAX_RISK_PCT,
                        "max_risk_usd": MAX_RISK_USD, "earn_days": EARN_DAYS, "ready_weeks": READY_WEEKS, "ready_days": READY_DAYS,
                        "ready_min_pts": READY_MIN_PTS},
           "items": items, "earn_excluded": excluded}
    (out / "expert_watch.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
    return res


def main(argv=None):
    """Rebuild from the files already in app/data (index.json rows, revc.json): python -m srs_app.expert_watch [--asof D]"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).resolve().parent.parent / "app" / "data"))
    ap.add_argument("--asof")
    a = ap.parse_args(argv)
    out = Path(a.data)
    rows = json.loads((out / "index.json").read_text()).get("rows", [])
    try:
        revc = json.loads((out / "revc.json").read_text())
    except Exception:
        revc = {}
    res = build(out, rows, revc, a.asof)
    print(f"expert watch: {len(res['items'])} ({sum(1 for x in res['items'] if x['tier'] == TIER_READY)} ready)")


if __name__ == "__main__":
    main()
