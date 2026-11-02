"""Expert zones become THE zone / Long of every stock (Eyal 2026-11-02, "מכאן והלאה נגדיר את האזור על פי המומחים").

Replaces the bot drawing computation (srs_app.bot_drawings v5) in the nightly pipeline:
  - every ticker with a valid expert-v7 zone (app/data/expert_zones.json, ok + trade) gets an EXPERT drawing pair in
    public.drawings: zone = [bottom, top] from the pivot week, Long = entry top / SL / TP of the expert trade
    (t_start = week after the last completed week, t_end = +20 weekly bars). Rows are source 'bot' (the column's check
    constraint), meta = {rule_version: expert-v7-..., expert: true, why: {...}}, note "EXPERT ...". The app and the
    report show them as "מומחים".
  - no valid expert zone (no clear retest) -> no zone and no Long: any live bot row is retired (-> not PASS).
  - every live bot drawing of the old method (v3d / v3e / v4 / v5, no meta.expert) is retired: status 'obsolete' +
    meta.obsolete {why: 'expert method 2026-11-02', at}. Nothing is hard-deleted; a JSON backup of the retired rows
    goes to /workspace/backups/bot_drawings_retired_<date>.json.
  - Eyal's own drawings (source user / tv, live) are HIS OVERRIDE: never modified, deleted or superseded; per kind -
    his zone replaces the expert zone, his Long the expert Long (his zone + the expert Long is possible). To go back to the expert levels he presses
    "חזרה לאזור המומחים" in the app (his rows -> obsolete with meta.reset_to_expert; the next sync / the app draws
    the expert pair).
  - an expert pair whose levels changed (zone moved / trade updated) is replaced; same levels -> kept.

    python -m srs_app.expert_drawings --drawings-json D.json [--zones app/data/expert_zones.json] --emit-sql
    (bot_drawings.main routes here: EXPERT_MODE)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

LIVE = ("active", "approved", "review")
RETIRE_WHY = "expert method 2026-11-02"
BACKUP_DIR = Path("/workspace/backups")
ZONES = Path(__file__).resolve().parent.parent / "app" / "data" / "expert_zones.json"
LONG_W_BARS = 20
TOL = 0.011


def is_expert(d: Dict[str, Any]) -> bool:
    m = d.get("meta") or {}
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except Exception:
            m = {}
    return bool(m.get("expert")) or str(m.get("rule_version", "")).startswith("expert")


def _monday(s: str) -> date:
    d = date.fromisoformat(s[:10])
    return d - timedelta(days=d.weekday())


def levels(t: str, z: Dict[str, Any], rule_version: str) -> Optional[Dict[str, Any]]:
    """Expert drawing pair for one ticker, or None (no clear retest -> no zone, no Long)."""
    if not z or not z.get("ok") or not z.get("trade"):
        return None
    tr = z["trade"]
    lw = z.get("last_week") or date.today().isoformat()
    t_start = (_monday(lw) + timedelta(days=7)).isoformat()
    t_end = (_monday(lw) + timedelta(days=7 * (1 + LONG_W_BARS))).isoformat()
    zs = z.get("pivot_week") or z.get("base_start") or z.get("breakout_week")
    why = {k: z.get(k) for k in ("pivot_week", "breakout_week", "breakout_close", "post_high", "score", "atr_w", "width_note")}
    why.update(retest_low=tr.get("retest_low"), risk_pct=tr.get("risk_pct"), notes=tr.get("notes"), tp_mm=tr.get("tp_mm"))
    return {"ticker": t, "zone_top": z["top"], "zone_bottom": z["bottom"], "zone_t_start": zs, "entry": tr["entry"],
            "stop": tr["sl"], "target": tr["tp"], "rr": tr.get("rr"), "t_start": t_start, "t_end": t_end,
            "meta": {"rule_version": rule_version, "expert": True, "why": why}}


def _same(rows: List[Dict[str, Any]], lv: Dict[str, Any], kinds=("zone", "long")) -> bool:
    near = lambda a, b: a is not None and b is not None and abs(float(a) - float(b)) <= TOL
    z = [d for d in rows if d.get("kind") == "zone"]
    lg = [d for d in rows if d.get("kind") == "long"]
    zok = len(z) == 1 and near(z[0].get("zone_top"), lv["zone_top"]) and near(z[0].get("zone_bottom"), lv["zone_bottom"]) if "zone" in kinds else not z
    lok = len(lg) == 1 and near(lg[0].get("entry"), lv["entry"]) and near(lg[0].get("stop"), lv["stop"]) and near(lg[0].get("target"), lv["target"]) if "long" in kinds else not lg
    return zok and lok


def plan(drawings: Iterable[Dict[str, Any]], zones_doc: Dict[str, Any]) -> Dict[str, Any]:
    """{insert: [levels], retire: {ticker: [rows]}, why: {ticker: reason}, his: [tickers with his override], keep: [..]}"""
    rv = zones_doc.get("rule_version") or "expert"
    zones = zones_doc.get("tickers", {})
    by_t: Dict[str, List[Dict[str, Any]]] = {}
    for d in drawings:
        if d.get("status") in LIVE:
            by_t.setdefault(str(d["ticker"]).upper(), []).append(d)
    out = {"insert": [], "retire": {}, "why": {}, "his": [], "keep": [], "none": []}
    for t in sorted(set(by_t) | set(zones)):
        rows = by_t.get(t, [])
        his = [d for d in rows if d.get("source") in ("user", "tv")]
        bots = [d for d in rows if d.get("source") == "bot"]
        old = [d for d in bots if not is_expert(d)]
        exp = [d for d in bots if is_expert(d)]
        lv = levels(t, zones.get(t), rv)
        if old:
            out["retire"].setdefault(t, []).extend(old)
            out["why"][t] = RETIRE_WHY
        his_kinds = {d.get("kind") for d in his if d.get("kind") in ("zone", "long")}
        if his:
            out["his"].append(t)
        if his_kinds:                             # his override wins per kind (his zone + expert Long is possible)
            dup = [d for d in exp if d.get("kind") in his_kinds]
            if dup:
                out["retire"].setdefault(t, []).extend(dup)
                out["why"][t] = "his own drawing is the override"
            exp = [d for d in exp if d.get("kind") not in his_kinds]
            if his_kinds == {"zone", "long"}:
                continue
        if lv is None:
            if t in zones:
                out["none"].append(t)
            if exp:
                out["retire"].setdefault(t, []).extend(exp)
                out["why"][t] = "no expert zone: " + str((zones.get(t) or {}).get("reason") or "not evaluated")[:120]
            continue
        kinds = [k for k in ("zone", "long") if k not in his_kinds]
        if exp and _same(exp, lv, kinds):
            out["keep"].append(t)
            continue
        if exp:
            out["retire"].setdefault(t, []).extend(exp)
            out["why"][t] = "expert levels changed"
        out["insert"].append({**lv, "kinds": kinds})
    return out


def sql_retire(drawing_id: str, why: str) -> str:
    from srs_app.sync import _lit
    return ("update public.drawings set status = 'obsolete', updated_at = now(), meta = coalesce(meta, '{}'::jsonb) || "
            f"jsonb_build_object('obsolete', jsonb_build_object('why', {_lit(why)}, 'at', now())) "
            f"where id = {_lit(drawing_id)} and source = 'bot' and status in ('active', 'approved', 'review');")


def emit_sql(pl: Dict[str, Any]) -> List[str]:
    from srs_app.sync import sql_insert_bot_drawing
    out = []
    for t, rows in pl["retire"].items():
        out += [sql_retire(str(d["id"]), pl["why"].get(t, RETIRE_WHY)) for d in rows if d.get("source") == "bot"]
    for lv in pl["insert"]:
        note = f"EXPERT {lv['meta']['rule_version']}: retest of the {lv['meta']['why'].get('breakout_week')} breakout"
        ks = lv.get("kinds", ("zone", "long"))
        if "zone" in ks:
            out.append(sql_insert_bot_drawing(lv["ticker"], "zone", zone_top=lv["zone_top"], zone_bottom=lv["zone_bottom"],
                                              t_start=lv["zone_t_start"], note=note, meta=lv["meta"]))
        if "long" in ks:
            out.append(sql_insert_bot_drawing(lv["ticker"], "long", entry=lv["entry"], stop=lv["stop"], target=lv["target"],
                                              t_start=lv["t_start"], t_end=lv["t_end"], note=note, meta=lv["meta"]))
    return out


def backup(pl: Dict[str, Any], today: Optional[str] = None, out_dir: Optional[Path] = None) -> Optional[Path]:
    rows = [d for rs in pl["retire"].values() for d in rs]
    if not rows:
        return None
    today = today or date.today().isoformat()
    p = (out_dir or BACKUP_DIR) / f"bot_drawings_retired_{today}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        cur = {str(r.get("id")): r for r in json.loads(p.read_text()).get("rows", [])}
    except Exception:
        cur = {}
    for r in rows:
        cur[str(r.get("id"))] = r
    p.write_text(json.dumps({"_doc": "Bot drawings retired by the expert sync (status 'obsolete' + meta.obsolete in "
                             "Supabase; restore = status 'active').", "rows": list(cur.values())}, indent=1, default=str))
    return p


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--drawings-json", required=True)
    ap.add_argument("--zones", default=str(ZONES))
    ap.add_argument("--emit-sql", action="store_true")
    ap.add_argument("--out")
    a, _ = ap.parse_known_args(argv)
    from srs_app.app_drawings import load_rows
    pl = plan(load_rows(Path(a.drawings_json)), json.loads(Path(a.zones).read_text()))
    if a.out:
        Path(a.out).write_text(json.dumps(pl, indent=1, default=str))
    bp = backup(pl)
    print(f"-- expert sync: insert {len(pl['insert'])}, keep {len(pl['keep'])}, retire "
          f"{sum(len(v) for v in pl['retire'].values())} rows / {len(pl['retire'])} tickers, his overrides {len(pl['his'])}, "
          f"no expert zone {len(pl['none'])}" + (f", backup {bp}" if bp else ""), file=sys.stderr)
    if a.emit_sql:
        print("\n".join(emit_sql(pl)))


if __name__ == "__main__":
    main()
