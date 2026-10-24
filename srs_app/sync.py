"""Read what Eyal edits in the web app (Supabase project wkkdblnykgolqijzagva).

The box has NO service key and RLS only lets azran4u@gmail.com read/write, so the bot does
NOT talk to Supabase from Python. It runs these SQL statements through its Supabase connector
(`execute_sql`, project_id "wkkdblnykgolqijzagva"), then feeds the JSON rows to the helpers below.

    from srs_app import sync
    sql = sync.SQL_ACTIVE_DRAWINGS              # -> execute_sql
    levels = sync.levels_by_ticker(rows)        # rows = the JSON list execute_sql returned
    sync.sql_command_done(42, "drew zone")      # -> execute_sql (mark a command handled)

Tables (public): drawings, labels, commands, watchlist — see README "Web app".
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

PROJECT_ID = "wkkdblnykgolqijzagva"

# ---------------- read ----------------
SQL_ACTIVE_DRAWINGS = """
select id, ticker, kind, zone_top, zone_bottom, entry, stop, target, t_start, t_end,
       source, status, note, created_at, updated_at
from public.drawings
where status in ('active', 'approved', 'review')
order by ticker, kind, updated_at desc;
""".strip()

# Source of truth per ticker for the scanner: the app's live rows = user + tv (imported, maybe edited
# in the app) + active/approved bot (approved by default since 2026-10-23). Excludes legacy review, rejected,
# obsolete, deleted.
SQL_SOURCE_OF_TRUTH = """
select distinct on (ticker, kind) id, ticker, kind, zone_top, zone_bottom, entry, stop, target, t_start,
       source, status, tv_key, updated_at
from public.drawings
where kind in ('zone', 'long')
  and status in ('active', 'approved')  -- bot rows included: approved by default (policy 2026-10-23)
order by ticker, kind, updated_at desc;
""".strip()

SQL_DRAWINGS_CHANGED_SINCE = """
select * from public.drawings where updated_at > {since} order by updated_at;
""".strip()

SQL_LATEST_LABELS = """
select distinct on (ticker, label) ticker, label, value, note, asof, created_at
from public.labels
order by ticker, label, asof desc, created_at desc;
""".strip()

SQL_PENDING_COMMANDS = """
select id, ticker, text, created_at
from public.commands
where status = 'pending'
order by created_at;
""".strip()


def _lit(v: Any) -> str:
    """SQL literal (the connector takes a plain SQL string)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(round(float(v), 4)) if isinstance(v, float) else str(v)
    return "'" + str(v).replace("'", "''") + "'"


def sql_drawings_for(ticker: str) -> str:
    return f"select * from public.drawings where ticker = {_lit(ticker.upper())} order by updated_at desc;"


def sql_drawings_changed_since(iso_ts: str) -> str:
    return SQL_DRAWINGS_CHANGED_SINCE.format(since=_lit(iso_ts))


# ---------------- write (bot side) ----------------
def sql_command_done(cmd_id: int, reply: str, error: bool = False) -> str:
    return (f"update public.commands set status = {_lit('error' if error else 'done')}, reply = {_lit(reply)}, "
            f"done_at = now() where id = {int(cmd_id)};")


def sql_insert_bot_drawing(ticker: str, kind: str, *, zone_top=None, zone_bottom=None, entry=None, stop=None,
                           target=None, t_start: Optional[str] = None, t_end: Optional[str] = None,
                           note: str = "BOT", status: str = "active", meta: Optional[Dict[str, Any]] = None) -> str:
    """Bot drawings go in as source='bot'. Policy 2026-10-23 (Eyal: "everything is approved unless I say otherwise"):
    status 'active' = approved by default, counts toward PASS like his own drawings; negative feedback in the app
    sets it to 'rejected'. meta = {rule_version, why} (jsonb) for feedback analysis."""
    import json
    cols = dict(ticker=ticker.upper(), kind=kind, zone_top=zone_top, zone_bottom=zone_bottom, entry=entry,
                stop=stop, target=target, t_start=t_start, t_end=t_end, source="bot", status=status, note=note)
    vals = [_lit(v) for v in cols.values()]
    if meta is not None:
        cols["meta"] = None
        vals.append(_lit(json.dumps(meta, separators=(",", ":"), default=str)) + "::jsonb")
    return (f"insert into public.drawings ({', '.join(cols)}) values ({', '.join(vals)}) "
            f"returning id;")


def sql_mark_obsolete(drawing_id: str) -> str:
    return f"update public.drawings set status = 'obsolete', updated_at = now() where id = {_lit(drawing_id)};"


# ---------------- parse ----------------
def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def rr(entry, stop, target) -> Optional[float]:
    e, s, t = _f(entry), _f(stop), _f(target)
    if e is None or s is None or t is None or e - s <= 0:
        return None
    return round((t - e) / (e - s), 2)


def levels_by_ticker(rows: Iterable[Dict[str, Any]], include_review: bool = False) -> Dict[str, Dict[str, Any]]:
    """Latest zone + long per ticker, in tv_drawings.json-like shape (zone_top/bottom, entry, sl, tp, rr).

    Bot drawings still in 'review' are skipped unless include_review (same rule as TradingView:
    not counted toward PASS until approved). Rejected / obsolete rows are always skipped.
    """
    out: Dict[str, Dict[str, Any]] = {}
    rows = sorted(rows, key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)
    for r in rows:
        st = r.get("status")
        if st in ("rejected", "obsolete", "deleted") or (st == "review" and not include_review):
            continue
        t = str(r["ticker"]).upper()
        d = out.setdefault(t, {"ticker": t, "zone_top": None, "zone_bottom": None, "entry": None, "sl": None,
                               "tp": None, "rr": None, "source": "app", "owner": set(), "ids": []})
        if r.get("kind") == "zone" and d["zone_top"] is None:
            d["zone_top"], d["zone_bottom"] = _f(r.get("zone_top")), _f(r.get("zone_bottom"))
            d["zone_start"] = r.get("t_start")
        elif r.get("kind") == "long" and d["entry"] is None:
            d["entry"], d["sl"], d["tp"] = _f(r.get("entry")), _f(r.get("stop")), _f(r.get("target"))
            d["rr"] = rr(d["entry"], d["sl"], d["tp"])
        else:
            continue
        d["owner"].add("bot-approved" if r.get("source") == "bot" and st == "approved" else r.get("source"))
        d["ids"].append(r.get("id"))
    for d in out.values():
        d["owner"] = sorted(x for x in d["owner"] if x)
    return out


def labels_by_ticker(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{ticker: {label: value}} from SQL_LATEST_LABELS rows; 'technical' -> True/False."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        v: Any = r.get("value")
        if r.get("label") == "technical":
            v = str(v).lower() in ("yes", "true", "1")
        out.setdefault(str(r["ticker"]).upper(), {})[r["label"]] = v
    return out


def pending_commands(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(id=int(r["id"]), ticker=r.get("ticker"), text=r.get("text"), created_at=r.get("created_at"))
            for r in rows]


# ---------------- watchlist / not interesting (app state file) ----------------
SQL_WATCHLIST = "select ticker, note, added_at from public.watchlist order by added_at;"

SQL_NOT_INTERESTING_ACTIVE = """
select distinct on (ticker) ticker, value, until, note, asof, created_at
from public.labels
where label = 'not_interesting'
order by ticker, asof desc, created_at desc;
""".strip()
# ^ latest mark per ticker; active = value='yes' and (until is null or until >= current_date).
# Pure-SQL filter of the active set:
SQL_NOT_INTERESTING_ACTIVE_ONLY = """
select ticker, until from (
  select distinct on (ticker) ticker, value, until
  from public.labels where label = 'not_interesting'
  order by ticker, asof desc, created_at desc
) x where value = 'yes' and (until is null or until >= current_date) order by ticker;
""".strip()

APP_STATE = "/workspace/stock-screener/app_state.json"

# Manual Fibonacci anchors Eyal placed in the app (label 'fib_anchor': JSON {low, low_date, high, high_date, at} or 'auto'
# = back to automatic). Latest mark per ticker; export_data uses them instead of the automatic anchor (Eyal 2026-10-24).
SQL_FIB_ANCHORS = """
select distinct on (ticker) ticker, value, asof, created_at
from public.labels
where label = 'fib_anchor'
order by ticker, asof desc, created_at desc;
""".strip()


def fib_anchors(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{ticker: {low, low_date, high, high_date}} from SQL_FIB_ANCHORS rows (latest per ticker; 'auto' / invalid -> none)."""
    import json
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        t = str(r["ticker"]).upper()
        k = (str(r.get("asof") or ""), str(r.get("created_at") or ""))
        if t not in best or k > best[t]["_k"]:
            best[t] = {"_k": k, "value": r.get("value")}
    out: Dict[str, Dict[str, Any]] = {}
    for t, b in best.items():
        try:
            v = json.loads(b["value"]) if b["value"] and b["value"] != "auto" else None
            lo, hi = float(v["low"]), float(v["high"])
            if hi > lo and str(v["low_date"]) < str(v["high_date"]):
                out[t] = {"low": lo, "low_date": str(v["low_date"])[:10], "high": hi, "high_date": str(v["high_date"])[:10]}
        except Exception:
            continue
    return out


def not_interesting_active(rows: Iterable[Dict[str, Any]], asof: Optional[str] = None) -> Dict[str, Optional[str]]:
    """{ticker: until|None} for rows from SQL_NOT_INTERESTING_ACTIVE(_ONLY) that are active on asof (YYYY-MM-DD, default today)."""
    from datetime import date
    day = asof or date.today().isoformat()
    out: Dict[str, Optional[str]] = {}
    for r in rows:
        if str(r.get("value", "yes")).lower() != "yes":
            continue
        u = r.get("until")
        u = str(u)[:10] if u else None
        if u is None or u >= day:
            out[str(r["ticker"]).upper()] = u
    return out


def write_app_state(watch_rows: Iterable[Dict[str, Any]], ni_rows: Iterable[Dict[str, Any]], path: str = APP_STATE,
                    fib_rows: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Save what the routine read via SQL (SQL_WATCHLIST, SQL_NOT_INTERESTING_ACTIVE) for the offline scripts:
    export_data (watchlist tickers get candles) and export_daily_report (not-interesting excluded from targets)."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    ni_rows = list(ni_rows)
    state = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "watchlist": sorted({str(r["ticker"]).upper() for r in watch_rows}),
        # keep every 'yes' mark with its until; activity is re-checked against the report date when read
        "not_interesting": {str(r["ticker"]).upper(): (str(r["until"])[:10] if r.get("until") else None)
                            for r in ni_rows if str(r.get("value", "yes")).lower() == "yes"},
    }
    if fib_rows is not None:
        state["fib_anchors"] = fib_anchors(fib_rows)
    else:  # keep what an earlier read stored
        old = _load_state(path).get("fib_anchors")
        if old:
            state["fib_anchors"] = old
    Path(path).write_text(json.dumps(state, indent=1) + "\n")
    return state


def _load_state(path) -> Dict[str, Any]:
    import json
    from pathlib import Path
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def watchlist_from_state(path=APP_STATE) -> List[str]:
    return [str(t).upper() for t in _load_state(path).get("watchlist", [])]


def fib_anchors_from_state(path=APP_STATE) -> Dict[str, Dict[str, Any]]:
    return {str(t).upper(): v for t, v in (_load_state(path).get("fib_anchors") or {}).items()}


def not_interesting_from_state(path=APP_STATE, asof: Optional[str] = None) -> set:
    ni = _load_state(path).get("not_interesting", {}) or {}
    return set(not_interesting_active([{"ticker": t, "value": "yes", "until": u} for t, u in ni.items()], asof))


def main() -> None:
    """python -m srs_app.sync --watch-json W --ni-json N [--fib-json F]  ->  /workspace/stock-screener/app_state.json
    W / N = execute_sql output (raw connector output or a JSON list) of SQL_WATCHLIST / SQL_NOT_INTERESTING_ACTIVE."""
    import argparse
    from pathlib import Path
    from srs_app.app_drawings import load_rows
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--watch-json", required=True)
    ap.add_argument("--ni-json", required=True)
    ap.add_argument("--fib-json", default=None, help="execute_sql output of SQL_FIB_ANCHORS (manual Fib anchors)")
    ap.add_argument("--out", default=APP_STATE)
    a = ap.parse_args()
    st = write_app_state(load_rows(Path(a.watch_json)), load_rows(Path(a.ni_json)), a.out,
                         load_rows(Path(a.fib_json)) if a.fib_json else None)
    print(f"app state: {len(st['watchlist'])} watchlist, {len(st['not_interesting'])} not-interesting marks, "
          f"{len(st.get('fib_anchors') or {})} manual fib anchors -> {a.out}")


if __name__ == "__main__":
    main()
