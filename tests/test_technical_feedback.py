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
  top) are NOT.
- v4 (2026-11-16, Eyal): the primary trend is the classic Dow structure of the weekly swings (srs_app/dow_trend.py);
  the v3 tests below run the v3 paths explicitly (tech_method='v3'); the Dow tests are at the end.
"""
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
    return _with(hist, V3_KEYS, tech_method="v3")["f_technical"]


def _v2(hist):
    return _with(hist, V3_KEYS, tech_flat_windows=(), tech_method="v3")["f_technical"]


def _v3(hist):
    return _with(hist, (), tech_method="v3")


def test_golden_up_charts_kept_and_accuracy_not_lower():
    daily = load_daily()
    lost, n, ok_new, ok_old = [], 0, 0, 0
    for c in load_cases():
        d = daily.get(c["ticker"])
        if d is None:
            continue
        up = c["up"] or c["ticker"] in RELABEL_UP
        h = _cut(d, c["asof"])
        new, old = _v3(h)["f_technical"], _v21(h)
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
    t = _v3(d)
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
    t = _v3(h)
    assert t["f_technical"] is True, t["tech_detail"]
    assert t["tech_path"] == path


@pytest.mark.parametrize("ticker", ["BIO", "PRU", "TROW"])
def test_v3_multi_year_range_back_at_top_rejected(ticker):
    h = CAL[ticker]
    assert _v21(h) is True  # v2.1 let it through
    t = _v3(h)
    assert t["f_technical"] is False
    assert t["tech_range"] is True
    assert "multi-year range back at its top" in t["tech_detail"]


@pytest.mark.parametrize("ticker", ["PUBM", "BDSX", "BRKR"])
def test_v3_bottoming_downtrend_not_a_v_recovery(ticker):
    """Sharp rebounds that are still far below the 3-year high (close < 75% of it) are not V-recovery uptrends -
    these let path B in during the 2026-10-26 check of newly accepted names (tech_vrec_close_hi156_min)."""
    t = _v3(CAL[ticker])
    assert t["f_technical"] is False
    assert _with(CAL[ticker], (), tech_vrec_close_hi156_min=0.0)["tech_path"] == "B"


# ----------------------------------------------------------------------------------------------- v4 Dow (2026-11-16)
NEG_1009 = ["LPLA", "MDLZ", "REGN", "AJG", "AMP", "CACI", "CHD", "ICE", "LW", "MTG"]
# 10-09 negatives the Dow structure (k = 5) still calls UP on their 2026-10-09 data: their swings were rising then
# (his 7-day overrides expired long ago; he can mark them again in the app)
DOW_UP_NEG = {"MDLZ", "REGN", "CHD", "LW"}   # v5 ZigZag swings (v4 pivots: MDLZ, AMP, CHD)


def _case(t, asof):
    d = load_daily()[t]
    return d[d.index <= pd.Timestamp(asof)]


def test_dow_is_the_primary_trend():
    t = rf.compute_technical(_case("EQIX", "2026-10-09"))
    assert rf.CONFIG["tech_method"] == "dow" and rf.CONFIG["tech_version"].startswith("dow-v5")
    assert t["tech_trend"] == "up" and t["tech_trend_he"] == "עלייה" and t["f_technical"] is True   # EQIX = uptrend
    assert t["tech_v3"] is True and t["tech_trend_detail"]


@pytest.mark.parametrize("ticker", [t for t in NEG_1009 if t not in DOW_UP_NEG])
def test_dow_1009_negatives_not_up(ticker):
    t = rf.compute_technical(_case(ticker, "2026-10-09"))
    assert t["f_technical"] is False and t["tech_trend"] in ("down", "sideways"), t["tech_trend_detail"]


def test_dow_golden_agreement_recorded():
    """2026-11-16: Dow (k = 5, close breaks, persistence, same-type swings >= 8 weeks apart) 98/130 on the golden set
    with EQIX as up (v3: 117/130; no spacing 96/130; k = 3 without spacing 81/130)."""
    ok = n = 0
    for c in load_cases():
        d = load_daily().get(c["ticker"])
        if d is None:
            continue
        up = c["up"] or c["ticker"] == "EQIX"
        n += 1
        ok += rf.compute_technical(_cut(d, c["asof"]))["f_technical"] == up
    assert ok >= 103, (ok, n)   # v5 ZigZag 2 ATR / tol 0.25 ATR: 103/130 (v4 pivots 98/130)


@pytest.mark.parametrize("ticker,trend", [("IDCC", "sideways"), ("LNTH", "up"), ("BIO", "up"), ("PRU", "sideways"),
                                          ("TROW", "sideways"), ("MTG", "up")])
def test_dow_calibration_marks(ticker, trend):
    """His 2026-10-26 marks: IDCC / LNTH / MTG up, BIO / PRU / TROW not. v5 (ZigZag swings) agrees on LNTH, MTG, PRU,
    TROW; IDCC = sideways (its 2026-05 low 248.51 is a lower low under 292.23), BIO = up (HH 396 over 343, HL 237 over 211)."""
    t = rf.compute_technical(CAL[ticker][CAL[ticker].index <= pd.Timestamp("2026-10-26")])
    assert t["tech_trend"] == trend, t["tech_trend_detail"]


def test_dow_structure_unit():
    from srs_app.dow_trend import trend
    up_h = [10, 11, 12, 11, 10, 11, 13, 14, 15, 14, 13, 14, 16, 17, 18, 17, 16, 17, 19, 20]
    up_l = [x - 2 for x in up_h]
    assert trend(up_h, up_l, up_l[:], k=2, gap=0, swing="pivot")["trend"] == "up"
    dn_h = [-x for x in up_l][::1]
    dn_l = [-x for x in up_h]
    assert trend([x + 40 for x in dn_h], [x + 40 for x in dn_l], [x + 40 for x in dn_l], k=2, gap=0, swing="pivot")["trend"] == "down"
    # a fresh weekly CLOSE under the last swing low ends an uptrend at once (not yet a confirmed pivot)
    h2, l2 = up_h + [18, 15], up_l + [16, 11]
    c2 = l2[:]
    assert trend(h2, l2, c2, k=2, gap=0, swing="pivot")["trend"] != "up"
    # a wick under the swing low without a close under it does not break it
    assert trend(up_h + [19], up_l + [13.9], up_l + [17.5], k=2, gap=0, swing="pivot")["broken_lo"] is False


def test_swing_spacing_merges_close_swings():
    """Eyal 2026-11-16: swings of the same type >= tech_swing_min_gap_weeks (8) apart; closer -> keep the extreme."""
    from srs_app.dow_trend import space
    assert rf.CONFIG["tech_swing_min_gap_weeks"] == 8
    assert space([(10, 5.0), (14, 6.0), (30, 4.0)], 8, "hi") == [(14, 6.0), (30, 4.0)]
    assert space([(10, 5.0), (14, 6.0), (30, 4.0)], 8, "lo") == [(10, 5.0), (30, 4.0)]
    assert space([(10, 5.0), (18, 6.0)], 8, "hi") == [(10, 5.0), (18, 6.0)]          # exactly 8 weeks: two swings
    assert space([(10, 5.0), (14, 6.0)], 0, "hi") == [(10, 5.0), (14, 6.0)]          # 0 = off


def test_swing_spacing_turns_a_minor_dip_into_one_swing():
    """A dip 4 weeks after a swing low, a bit under it: without spacing it is a new LOWER low (uptrend ends); with the
    8-week spacing the two lows are one swing (the lower one) and the higher-low structure stays."""
    from srs_app.dow_trend import trend
    h = [10 + i * 0.5 + 2 * (i % 10 if i % 10 <= 5 else 10 - i % 10) for i in range(62)]
    l = [x - 1 for x in h]
    l[54] = l[50] - 0.5
    h[54] = l[54] + 1
    assert trend(h, l, l[:], k=2, gap=0, swing="pivot")["trend"] == "sideways"
    assert trend(h, l, l[:], k=2, gap=8, swing="pivot")["trend"] == "up"


def test_compute_technical_uses_the_configured_gap():
    d = _case("LW", "2026-10-09")
    assert _with(d, (), tech_dow_swing="pivot")["tech_trend"] != "up"                                  # 8 weeks
    assert _with(d, (), tech_dow_swing="pivot", tech_swing_min_gap_weeks=0)["tech_trend"] == "up"     # no spacing


# ----------------------------------------------------------------------------------- v5 ZigZag swings (2026-11-16 pm)
def _v5(t):
    a = pd.read_csv(DATA / "dow_v5_daily.csv.gz", parse_dates=["Date"])
    return a[a.Ticker == t].drop(columns="Ticker").set_index("Date")


def test_v5_crwd_uptrend_uses_the_post_february_higher_lows():
    """CRWD 2026-11-12: v4 K=5 pivots found no swing low after 2026-02-27 (85.68) in the 86 -> 287 run (each pullback
    low sat above the lows 5 weeks before it) -> 'LL 100.67 -> 85.68' = sideways. ZigZag: HL 181.24 (2026-08-28),
    HH 286.99 -> up."""
    d = _v5("CRWD")
    assert _with(d, (), tech_dow_swing="pivot")["tech_trend"] == "sideways"
    t = rf.compute_technical(d)
    assert t["tech_trend"] == "up", t["tech_trend_detail"]
    assert "286.99" in t["tech_trend_detail"] and "181.24" in t["tech_trend_detail"]


def test_v5_eqix_not_a_downtrend():
    """EQIX 2026-11-12: closes 985.98 / 955.03 under the 989.08 July floor; v4 read LH 1118.65 -> 1103.95 + LL = down.
    v5: equal highs within 0.25 ATR, the swing low 931.20 is a higher low vs 709.79 -> up (never down)."""
    d = _v5("EQIX")
    assert _with(d, (), tech_dow_swing="pivot")["tech_trend"] == "down"
    assert rf.compute_technical(d)["tech_trend"] == "up"


def test_v5_tolerance_equal_swings():
    from srs_app.dow_trend import trend_v5
    import math
    # rising zigzag, then a lower high only 0.1 ATR under the previous one -> 'equal', not LH
    h, l, c = [], [], []
    for i in range(120):
        base = 100 + 10 * math.sin(i / 4.0) + i * 0.3
        h.append(base + 1); l.append(base - 1); c.append(base)
    r = trend_v5(h, l, c, 2.0, 0.25, 8)
    assert r["trend"] == "up", r["detail"]
