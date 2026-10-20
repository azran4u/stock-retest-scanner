"""Import TradingView drawings (tv_drawings.json) into the app's Supabase `drawings` table.

Emits idempotent SQL: every TV zone / Long position becomes one row with source='tv' and a stable
`tv_key`; inserts use ON CONFLICT (tv_key) DO NOTHING, so a row Eyal edited or deleted (status
'deleted') in the app is never overwritten or resurrected.

tv_key = "<TICKER>:<kind>:<values>" built from the drawing's original TV levels
(zone: top/bottom, long: entry/stop/target, 2 dp). A drawing he moves in TradingView therefore
comes in as a NEW row on the next import (the old row stays as it is in the app).

TV drawings the nightly read marked as the bot's own, still "BOT - review needed" (tv source 'bot'),
are imported with status='review' (standing rule: bot drawings are not counted until approved);
everything else is status='active'.

The box has no Supabase service key: run the emitted SQL through the Supabase connector
(execute_sql, project wkkdblnykgolqijzagva). Each batch returns one row {"inserted": N}.

    python -m srs_app.import_tv --out /workspace/tv_import_sql     # writes batch_001.sql, ...
    python -m srs_app.import_tv --print                             # all batches to stdout
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

TV_DRAWINGS = Path(os.environ.get("SRS_TV_DRAWINGS", "/workspace/stock-screener/tv_drawings.json"))
COLS = ["ticker", "kind", "zone_top", "zone_bottom", "entry", "stop", "target", "t_start",
        "source", "status", "note", "tv_key"]


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _k(v: Optional[float]) -> str:
    return f"{v:.2f}"


def _lit(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def rows_from_tv(tv: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ticker in sorted(tv):
        d = tv[ticker]
        if not d.get("found"):
            continue
        owner = (d.get("source_override") or d.get("source") or "").strip()
        review = owner == "bot"
        status = "review" if review else "active"
        base_note = f"TV {owner or 'drawing'} read {d.get('read_date') or '?'}"
        if review:
            base_note += " - BOT review needed"
        t = ticker.upper()
        zt, zb = _num(d.get("zone_top")), _num(d.get("zone_bottom"))
        if zt is not None and zb is not None:
            top, bot = max(zt, zb), min(zt, zb)
            rows.append(dict(ticker=t, kind="zone", zone_top=top, zone_bottom=bot, entry=None, stop=None,
                             target=None, t_start=d.get("zone_start") or None, source="tv", status=status,
                             note=base_note, tv_key=f"{t}:zone:{_k(top)}-{_k(bot)}"))
        e, s, tp = _num(d.get("entry")), _num(d.get("sl")), _num(d.get("tp"))
        if e is not None and s is not None and tp is not None:
            rows.append(dict(ticker=t, kind="long", zone_top=None, zone_bottom=None, entry=e, stop=s, target=tp,
                             t_start=d.get("long_start") or None, source="tv", status=status,
                             note=base_note, tv_key=f"{t}:long:{_k(e)}/{_k(s)}/{_k(tp)}"))
    return rows


def sql_batch(rows: List[Dict[str, Any]]) -> str:
    values = ",\n  ".join("(" + ", ".join(_lit(r[c]) for c in COLS) + ")" for r in rows)
    return (f"with ins as (\n insert into public.drawings ({', '.join(COLS)}) values\n  {values}\n"
            f" on conflict (tv_key) do nothing\n returning 1\n) select count(*) as inserted from ins;")


def batches(rows: List[Dict[str, Any]], size: int = 60) -> List[str]:
    return [sql_batch(rows[i:i + size]) for i in range(0, len(rows), size)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tv", default=str(TV_DRAWINGS))
    ap.add_argument("--out", default="/workspace/tv_import_sql", help="directory for batch_NNN.sql")
    ap.add_argument("--size", type=int, default=60)
    ap.add_argument("--print", action="store_true", help="print batches to stdout instead of files")
    a = ap.parse_args()
    rows = rows_from_tv(json.loads(Path(a.tv).read_text()))
    bs = batches(rows, a.size)
    kinds = {k: sum(r["kind"] == k for r in rows) for k in ("zone", "long")}
    if a.print:
        print("\n\n".join(bs))
    else:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for f in out.glob("batch_*.sql"):
            f.unlink()
        for i, b in enumerate(bs, 1):
            (out / f"batch_{i:03d}.sql").write_text(b + "\n")
        print(f"tv import: {len(rows)} rows ({kinds['zone']} zones, {kinds['long']} longs, "
              f"{sum(r['status'] == 'review' for r in rows)} bot-review) -> {len(bs)} batches in {out}")


if __name__ == "__main__":
    main()
