"""Read what Eyal edits in the web app (Supabase project wkkdblnykgolqijzagva).

The box has NO service key and RLS only lets azran4u@gmail.com read/write, so the bot does
NOT talk to Supabase from Python. It runs these SQL statements through its Supabase connector
(`execute_sql`, project_id "wkkdblnykgolqijzagva"), then feeds the JSON rows to the helpers below.

    from srs_app import sync
    sql = sync.SQL_ACTIVE_DRAWINGS              # -> execute_sql
    levels = sync.levels_by_ticker(rows)        # rows = the JSON list execute_sql returned
    sync.sql_command_done(42, "drew zone")      # -> execute_sql (mark a command handled)

Tables (public): drawings, labels, commands — see README "Web app".
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
                           target=None, t_start: Optional[str] = None, note: str = "BOT - review needed") -> str:
    """Bot proposals always go in as source='bot', status='review' (Eyal approves / rejects in the app)."""
    cols = dict(ticker=ticker.upper(), kind=kind, zone_top=zone_top, zone_bottom=zone_bottom, entry=entry,
                stop=stop, target=target, t_start=t_start, source="bot", status="review", note=note)
    return (f"insert into public.drawings ({', '.join(cols)}) values ({', '.join(_lit(v) for v in cols.values())}) "
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
        if st in ("rejected", "obsolete") or (st == "review" and not include_review):
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
