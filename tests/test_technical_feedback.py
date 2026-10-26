"""Regression for compute_technical (report_filters 'technical' = PRIMARY weekly uptrend) from app feedback.

- Golden charts (tests/golden_trend.yaml: his own drawings / named calls): v3 accuracy must not drop below v2.1, and
  every golden 'up' chart v2.1 called technical stays technical except the documented v3 range rejections.
  MTG and EQIX are scored as 'up' here (Eyal 2026-10-26: MTG = up in the calibration marks; EQIX IS a primary
  uptrend - the 2026-10-09 mark meant 'not technical', not 'no uptrend'). The yaml itself is left unchanged
  because it is also srs.trend's golden set.
- CRGY (2026-10-23, 'structure not suitable', command 4): a 3-year 7-15.5 range that ran back to its top passed v2
  (near new high + 30w EMA +16.8%); v2.1+ rejects it as a multi-year sideways range.
- v3 (2026-10-26, Eyal's calibration answers): LNTH (V-recovery ~6.5 ATR below the high), IDCC (strong rise then
  sideways near the high) and MTG (slow riser) ARE primary uptrends; BIO, PRU, TROW (multi-year range back at its
  top) are NOT."""
from pathlib import Path

import pandas as pd
import pytest

import report_filters as rf
from srs.golden import load_cases, load_daily

DATA = Path(__file__).resolve().parent / "data"
V3_KEYS = [k for k in rf.CONFIG if k.startswith(("tech_slow_", "tech_vrec_", "tech_cons_", "tech_range_"))]
RELABEL_UP = {"MTG", "EQIX"}
# golden 'up' drawings (dated 2026-09/10) that v3 rejects as a multi-year range back at its top (R2 < 0.2 and
# 30w EMA < +20% in 52w) - the same shape as BIO / PRU / TROW that Eyal called NOT an uptrend on 2026-10-26
V3_RANGE_LOSSES = {"SJM", "VRTX"}


def _cut(d, asof):
    return d[d.index <= pd.Timestamp(asof)]


def _with(hist, drop_keys=(), **over):
    saved = {k: rf.CONFIG.pop(k) for k in drop_keys}
    old = {k: rf.CONFIG[k] for k in over}
    rf.CONFIG.update(over)
    try:
        return rf.compute_technical(hist)
    finally:
        rf.CONFIG.update(old)
        rf.CONFIG.update(saved)


def _v21(hist):
    return _with(hist, V3_KEYS)["f_technical"]


def _v2(hist):
    return _with(hist, V3_KEYS, tech_flat_windows=())["f_technical"]


def test_golden_up_charts_kept_and_accuracy_not_lower():
    daily = load_daily()
    lost, n, ok_new, ok_old = [], 0, 0, 0
    for c in load_cases():
        d = daily.get(c["ticker"])
        if d is None:
            continue
        up = c["up"] or c["ticker"] in RELABEL_UP
        h = _cut(d, c["asof"])
        new, old = rf.compute_technical(h)["f_technical"], _v21(h)
        n += 1
        ok_new += new == up
        ok_old += old == up
        if up and old and not new:
            lost.append(c["ticker"])
    assert set(lost) <= V3_RANGE_LOSSES, f"v3 rejects golden up charts: {sorted(set(lost) - V3_RANGE_LOSSES)}"
    assert ok_new >= ok_old + 4, (ok_new, ok_old, n)  # 2026-10-26: v3 116/130 vs v2.1 112/130 (MTG, EQIX as up)


def test_crgy_multi_year_range_not_technical():
    d = pd.read_csv(DATA / "feedback_crgy_daily.csv.gz", parse_dates=["Date"]).set_index("Date")
    assert _v2(d) is True  # what let it through
    t = rf.compute_technical(d)
    assert t["f_technical"] is False
    assert "range" in t["tech_detail"]


def _calib():
    d = pd.read_csv(DATA / "calib_v3_daily.csv.gz", parse_dates=["Date"])
    return {t: g.drop(columns="Ticker").set_index("Date") for t, g in d.groupby("Ticker")}


CAL = _calib()


@pytest.mark.parametrize("ticker,path", [("LNTH", "B"), ("IDCC", "C"), ("MTG", "A")])
def test_v3_calibration_uptrends(ticker, path):
    h = CAL[ticker]
    assert _v21(h) is False  # v2.1 missed it
    t = rf.compute_technical(h)
    assert t["f_technical"] is True, t["tech_detail"]
    assert t["tech_path"] == path


@pytest.mark.parametrize("ticker", ["BIO", "PRU", "TROW"])
def test_v3_multi_year_range_back_at_top_rejected(ticker):
    h = CAL[ticker]
    assert _v21(h) is True  # v2.1 let it through
    t = rf.compute_technical(h)
    assert t["f_technical"] is False
    assert t["tech_range"] is True
    assert "multi-year range back at its top" in t["tech_detail"]


@pytest.mark.parametrize("ticker", ["PUBM", "BDSX", "BRKR"])
def test_v3_bottoming_downtrend_not_a_v_recovery(ticker):
    """Sharp rebounds that are still far below the 3-year high (close < 75% of it) are not V-recovery uptrends -
    these let path B in during the 2026-10-26 check of newly accepted names (tech_vrec_close_hi156_min)."""
    t = rf.compute_technical(CAL[ticker])
    assert t["f_technical"] is False
    assert _with(CAL[ticker], (), tech_vrec_close_hi156_min=0.0)["tech_path"] == "B"
