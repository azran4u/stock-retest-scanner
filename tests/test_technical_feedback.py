"""Regression for compute_technical (report_filters 'technical' = clear weekly uptrend) from app feedback.

- Every golden 'up' chart (tests/golden_trend.yaml: his own drawings / named technical) that v2 already called
  technical must stay technical, and v2's golden accuracy must not drop.
- CRGY (2026-10-23, 'structure not suitable', command 4): a 3-year 7-15.5 range that ran back to its top passed v2
  (near new high + 30w EMA +16.8%); v2.1 rejects it as a multi-year sideways range."""
from pathlib import Path

import pandas as pd

import report_filters as rf
from srs.golden import load_cases, load_daily

DATA = Path(__file__).resolve().parent / "data"


def _cut(d, asof):
    return d[d.index <= pd.Timestamp(asof)]


def _v2(hist):
    old = rf.CONFIG.get("tech_flat_windows")
    rf.CONFIG["tech_flat_windows"] = ()
    try:
        return rf.compute_technical(hist)["f_technical"]
    finally:
        rf.CONFIG["tech_flat_windows"] = old


def test_golden_up_charts_unchanged_and_accuracy_kept():
    daily = load_daily()
    lost, n, ok_new, ok_old = [], 0, 0, 0
    for c in load_cases():
        d = daily.get(c["ticker"])
        if d is None:
            continue
        h = _cut(d, c["asof"])
        new, old = rf.compute_technical(h)["f_technical"], _v2(h)
        n += 1
        ok_new += new == c["up"]
        ok_old += old == c["up"]
        if c["up"] and old and not new:
            lost.append(c["ticker"])
    assert not lost, f"flat-range rule rejects his golden up charts: {lost}"
    assert ok_new >= ok_old, (ok_new, ok_old, n)


def test_crgy_multi_year_range_not_technical():
    d = pd.read_csv(DATA / "feedback_crgy_daily.csv.gz", parse_dates=["Date"]).set_index("Date")
    assert _v2(d) is True  # what let it through
    t = rf.compute_technical(d)
    assert t["f_technical"] is False
    assert "multi-year sideways range" in t["tech_detail"]
