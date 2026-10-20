"""Golden-set evaluation for srs.trend (used by tests/test_golden_trend.py and tools/tune_trend.py)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

from .trend import trend
from .weekly import to_weekly

TESTS = Path(__file__).resolve().parent.parent / "tests"
GOLDEN_YAML = TESTS / "golden_trend.yaml"
GOLDEN_DATA = TESTS / "data" / "golden_daily.csv.gz"


def load_cases(path: Path = GOLDEN_YAML) -> List[Dict[str, Any]]:
    return yaml.safe_load(Path(path).read_text())["cases"]


def load_daily(path: Path = GOLDEN_DATA) -> Dict[str, pd.DataFrame]:
    a = pd.read_csv(path, parse_dates=["Date"])
    return {t: g.drop(columns="Ticker").set_index("Date").sort_index() for t, g in a.groupby("Ticker")}


def evaluate(params: Optional[Dict[str, Any]] = None, cases=None, daily=None) -> Dict[str, Any]:
    """Predicted up = trend(...)['trend'] == 'up' on completed weeks as of each case's asof."""
    params = params or {}
    cases = cases if cases is not None else load_cases()
    daily = daily if daily is not None else load_daily()
    rows = []
    for c in cases:
        d = daily.get(c["ticker"])
        if d is None:
            rows.append({**c, "pred": None, "trend": None, "reason": "no data"})
            continue
        w = to_weekly(d, asof=c["asof"], drop_incomplete=True)
        r = trend(w, **params)
        rows.append({**c, "pred": r["trend"] == "up", "trend": r["trend"], "reason": r["reason"]})
    ev = [r for r in rows if r["pred"] is not None]
    tp = sum(r["up"] and r["pred"] for r in ev)
    tn = sum((not r["up"]) and (not r["pred"]) for r in ev)
    fp = sum((not r["up"]) and r["pred"] for r in ev)
    fn = sum(r["up"] and (not r["pred"]) for r in ev)
    pos, neg = tp + fn, tn + fp
    return {"rows": rows, "tp": tp, "tn": tn, "fp": fp, "fn": fn, "n": len(ev),
            "accuracy": (tp + tn) / len(ev) if ev else 0.0,
            "recall_up": tp / pos if pos else 0.0, "recall_not_up": tn / neg if neg else 0.0,
            "balanced_accuracy": ((tp / pos if pos else 0) + (tn / neg if neg else 0)) / 2,
            "missing": [r["ticker"] for r in rows if r["pred"] is None]}


def confusion_text(e: Dict[str, Any]) -> str:
    return (f"                 pred up   pred not-up\n"
            f"label up         {e['tp']:7d}   {e['fn']:11d}\n"
            f"label not-up     {e['fp']:7d}   {e['tn']:11d}\n"
            f"accuracy {e['accuracy']:.3f}  balanced {e['balanced_accuracy']:.3f}  "
            f"(up recall {e['recall_up']:.3f}, not-up recall {e['recall_not_up']:.3f}, n={e['n']})")
