"""App drawings -> the scanner's drawing store format (same shape as tv_drawings.json).

After TradingView is retired the web app (Supabase `drawings`) is the only drawing source.
The bot runs SQL_APP_DRAWINGS through the Supabase connector (execute_sql, project
wkkdblnykgolqijzagva), saves the returned JSON rows to a file, and runs

    python -m srs_app.app_drawings --from-json /workspace/stock-screener/app_drawings_rows.json

which writes /workspace/stock-screener/app_drawings.json. export_daily_report.py uses that file
instead of tv_drawings.json when it exists (PASS / R:R / needs drawing / review then come from the app).

Per ticker (newest row per kind wins):
  - user, tv (imported, maybe edited in the app) and active / approved bot rows -> counted
    (source_override "user": counts toward PASS like a user drawing). Policy 2026-10-23: bot drawings
    are approved by default; they keep bot_drawn=True (shown as "bot-approved" in the report);
  - legacy 'review' rows (none left after 2026-10-23) -> owner "bot", not counted — only when the
    ticker has no counted row of that kind; 'rejected' (negative feedback) never counts;
  - deleted / rejected / obsolete rows are ignored;
  - zone without long -> drawing_status "Rectangle only, no Long Position" (partial, same as TV);
    long without zone -> "LP only, no Rectangle".
Tickers present in tv_drawings.json but with no live app row keep found=false records
(lines-only notes stay; a ticker whose drawings were all deleted in the app becomes "no drawing").
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

TV_STORE = Path("/workspace/stock-screener/tv_drawings.json")
OUT = Path("/workspace/stock-screener/app_drawings.json")

SQL_APP_DRAWINGS = """
select id, ticker, kind, zone_top, zone_bottom, entry, stop, target, t_start, source, status, tv_key, note,
       created_at, updated_at
from public.drawings
where kind in ('zone', 'long') and status in ('active', 'approved', 'review')
order by ticker, kind, updated_at desc;
""".strip()


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _rr(e, s, t) -> Optional[float]:
    if e is None or s is None or t is None or e - s <= 0:
        return None
    return round((t - e) / (e - s), 4)


def _counts(r: Dict[str, Any]) -> bool:
    """active or approved rows count like a user drawing - including bot rows (policy 2026-10-23: bot drawings are
    approved by default; negative feedback sets them to 'rejected', which never counts). Legacy 'review' rows don't."""
    return r.get("status") in ("approved", "active")


def build_store(rows: Iterable[Dict[str, Any]], tv_store: Optional[Dict[str, Dict[str, Any]]] = None,
                now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    now = now or datetime.now(ZoneInfo("Asia/Jerusalem"))
    tv_store = tv_store or {}
    by_t: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in rows:
        if r.get("status") not in ("active", "approved", "review") or r.get("kind") not in ("zone", "long"):
            continue
        by_t.setdefault(str(r["ticker"]).strip().upper(), {}).setdefault(r["kind"], []).append(r)

    out: Dict[str, Dict[str, Any]] = {}
    for t, kinds in by_t.items():
        pick: Dict[str, Dict[str, Any]] = {}
        owner_user = False
        for kind, rs in kinds.items():
            rs = sorted(rs, key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
            good = [x for x in rs if _counts(x)]
            if good:
                pick[kind] = good[0]
                owner_user = True
            else:
                pick[kind] = rs[0]  # review proposal
        z, lg = pick.get("zone"), pick.get("long")
        if owner_user:  # mixing a counted row with a review proposal of the other kind: drop the proposal
            if z is not None and not _counts(z):
                z = None
            if lg is not None and not _counts(lg):
                lg = None
        zt, zb = (_f(z.get("zone_top")), _f(z.get("zone_bottom"))) if z else (None, None)
        if zt is not None and zb is not None and zt < zb:
            zt, zb = zb, zt
        e, s, tp = (_f(lg.get("entry")), _f(lg.get("stop")), _f(lg.get("target"))) if lg else (None, None, None)
        upd = max(str(x.get("updated_at") or x.get("created_at") or "") for x in (z, lg) if x) if (z or lg) else ""
        prev = tv_store.get(t, {})
        rec: Dict[str, Any] = {
            "found": True, "zone_top": zt, "zone_bottom": zb, "entry": e, "sl": s, "tp": tp, "rr": _rr(e, s, tp),
            "read_at": now.isoformat(timespec="seconds"), "read_date": now.date().isoformat(),
            "symbol": prev.get("symbol"), "source": "user" if owner_user else "bot",
            "drawing_source": "app", "app_updated_at": upd or None,
            "app_ids": [x.get("id") for x in (z, lg) if x],
            "zone_start": z.get("t_start") if z else None,
        }
        if owner_user:
            rec["source_override"] = "user"
            if all(x.get("source") == "bot" for x in (z, lg) if x):
                rec["bot_drawn"] = True  # auto-approved bot drawing: counts, but marked as bot-drawn
        if z and not lg:
            rec["drawing_status"] = "Rectangle only, no Long Position"
        elif lg and not z:
            rec["drawing_status"] = "LP only, no Rectangle"
        for k in ("screenshot", "screenshot_at", "screenshot_date"):
            if prev.get(k):
                rec[k] = prev[k]
        out[t] = rec

    for t, prev in tv_store.items():  # tickers with no live app drawing
        t = str(t).strip().upper()
        if t in out:
            continue
        if prev.get("found"):  # had a TV drawing, all its app rows were deleted / rejected
            out[t] = {"found": False, "zone_top": None, "zone_bottom": None, "entry": None, "sl": None, "tp": None,
                      "rr": None, "read_at": now.isoformat(timespec="seconds"), "read_date": now.date().isoformat(),
                      "symbol": prev.get("symbol"), "source": "", "drawing_source": "app",
                      "drawing_status": "deleted in app"}
        else:
            out[t] = dict(prev, drawing_source="tv-legacy")
    return dict(sorted(out.items()))


def load_rows(path: Path) -> List[Dict[str, Any]]:
    """A JSON list of rows, or the Supabase connector's raw execute_sql output
    ({"result": "...<untrusted-data-…>[ rows ]</untrusted-data-…>..."}) saved with write_to_file."""
    raw: Any = json.loads(path.read_text())
    if isinstance(raw, dict):
        raw = raw.get("rows", raw.get("result", raw))
    if isinstance(raw, str):
        i = raw.find("[")
        raw, _ = json.JSONDecoder().raw_decode(raw[i:]) if i >= 0 else ([], 0)
    if not isinstance(raw, list):
        raise ValueError(f"{path}: no row list found")
    return [r for r in raw if isinstance(r, dict)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-json", required=True, help="JSON rows from execute_sql(SQL_APP_DRAWINGS) (a list, "
                    "or the connector's {'result': ...} wrapper)")
    ap.add_argument("--tv", default=str(TV_STORE), help="legacy TradingView store (symbols / screenshots / lines-only)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--print-sql", action="store_true")
    a = ap.parse_args()
    if a.print_sql:
        print(SQL_APP_DRAWINGS)
        return
    rows = load_rows(Path(a.from_json))
    tv = json.loads(Path(a.tv).read_text()) if Path(a.tv).exists() else {}
    store = build_store(rows, tv)
    Path(a.out).write_text(json.dumps(store, indent=2) + "\n")
    found = [v for v in store.values() if v.get("found")]
    print(f"app drawings: {len(rows)} rows -> {len(found)} tickers with a drawing "
          f"({sum(v.get('source') == 'user' for v in found)} counted, {sum(v.get('source') == 'bot' for v in found)} "
          f"bot review, {sum(bool(v.get('drawing_status')) for v in found)} partial) -> {a.out}")


if __name__ == "__main__":
    main()
