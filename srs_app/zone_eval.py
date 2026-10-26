"""Zone rule vs Eyal's own drawings (ground truth): for every zone of his (app drawings source user / tv, plus
bot drawings he edited = meta.bot_before) compute what the bot rule picks as of the date he had it, and the
overlap IoU = |his ∩ bot| / |his ∪ bot| of the price bands. match = IoU >= 0.3 (the drawing-learn convention).
Usage: python -m srs_app.zone_eval --drawings-json D.json [--scoring v5 v4] [--out CSV]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

TV_STORE = Path("/workspace/stock-screener/tv_drawings.json")


def iou(a0: float, a1: float, b0: float, b1: float) -> float:
    a0, a1 = sorted((a0, a1)); b0, b1 = sorted((b0, b1))
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def truth(drawings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """His zones: newest live user/tv zone per ticker; as-of = TradingView read date for tv rows (when the store has
    the same zone), else the row's creation date."""
    try:
        tvs = json.loads(TV_STORE.read_text())
    except Exception:
        tvs = {}
    out: Dict[str, Dict[str, Any]] = {}
    for d in drawings:
        if d.get("kind") != "zone" or d.get("source") not in ("user", "tv") or d.get("status") not in ("active", "approved"):
            continue
        if d.get("zone_top") in (None, "") or d.get("zone_bottom") in (None, ""):
            continue
        t = str(d["ticker"]).upper()
        asof = str(d.get("created_at") or "")[:10]
        rec = tvs.get(t) or {}
        if d.get("source") == "tv" and rec.get("found") and rec.get("read_date"):
            asof = min(asof, str(rec["read_date"])[:10]) if asof else str(rec["read_date"])[:10]
        row = {"ticker": t, "zb": float(d["zone_bottom"]), "zt": float(d["zone_top"]), "asof": asof,
               "source": d.get("source"), "updated_at": str(d.get("updated_at") or "")}
        if t not in out or row["updated_at"] > out[t]["updated_at"]:
            out[t] = row
    return sorted(out.values(), key=lambda r: r["ticker"])


def evaluate(rows: List[Dict[str, Any]], scoring: str) -> List[Dict[str, Any]]:
    from srs_app import bot_drawings as B
    old = B.ZONE_SCORING
    B.ZONE_SCORING = scoring
    res = []
    try:
        for r in rows:
            try:
                b = B.compute(r["ticker"], r["asof"])
            except Exception as exc:  # missing history etc.
                b = {"has_level": False, "reason": f"error: {exc}"}
            if b.get("has_level"):
                q = iou(r["zb"], r["zt"], b["zone_bottom"], b["zone_top"])
                res.append(dict(r, scoring=scoring, bot_zb=b["zone_bottom"], bot_zt=b["zone_top"], iou=round(q, 3), match=q >= 0.3))
            else:
                res.append(dict(r, scoring=scoring, bot_zb=None, bot_zt=None, iou=0.0, match=False, reason=b.get("reason")))
    finally:
        B.ZONE_SCORING = old
    return res


def main() -> None:
    import pandas as pd
    from srs_app.app_drawings import load_rows
    ap = argparse.ArgumentParser()
    ap.add_argument("--drawings-json", required=True)
    ap.add_argument("--scoring", nargs="+", default=["touches", "v5"])
    ap.add_argument("--out")
    a = ap.parse_args()
    rows = truth(load_rows(Path(a.drawings_json)))
    allr = []
    for sc in a.scoring:
        e = evaluate(rows, sc)
        allr += e
        df = pd.DataFrame(e)
        drawn = df[df.bot_zb.notna()]
        print(f"{sc}: {len(df)} zones of his; bot drew {len(drawn)}; match (IoU>=0.3) {int(df.match.sum())}/{len(df)} "
              f"= {df.match.mean():.1%}; mean IoU {df.iou.mean():.3f} (drawn only {drawn.iou.mean():.3f})")
    if a.out:
        pd.DataFrame(allr).to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
