"""f_no_red_vol_week (Eyal 2026-10-23, example CLMT): a healthy red last COMPLETED weekly candle on
above-average volume = 'red high-volume last week'. Core gate since 2026-11-09; since 2026-11-16 it blocks ONLY when
that week closed below the zone in use (the planned SL; zone bottom without a Long). Most tests here pass SL_ABOVE
(a stop above every close = the zone broke) to check the candle / week detection itself.

healthy red = Close < Open and body >= 50% of the week's range; above average = the week's average daily
volume > the average daily volume of the 30 trading days before the week."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import report_filters as rf

DATA = Path(__file__).parent / "data"
AFTER_CLOSE = pd.Timestamp("2026-10-23 17:00", tz="America/New_York")   # Fri after 16:30 NY
BEFORE_1630 = pd.Timestamp("2026-10-23 16:15", tz="America/New_York")   # Fri after the cash close, before 16:30


def _daily(last_week, base_vol=1_000_000, weeks=12):
    """Flat 100 bars for `weeks` weeks ending Fri 2026-10-16, then the week of 2026-10-19..23 = last_week
    (list of (o, h, l, c, v) per day)."""
    idx = pd.bdate_range(end="2026-10-16", periods=weeks * 5)
    rows = [(100.0, 101.0, 99.0, 100.0, base_vol) for _ in idx]
    idx = idx.append(pd.bdate_range("2026-10-19", periods=len(last_week)))
    rows += list(last_week)
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close", "Volume"], dtype=float)


def _week(o, c, h, l, vol):
    """5 sessions forming one weekly candle open o, close c, high h, low l, each day volume vol."""
    path = np.linspace(o, c, 6)
    out = []
    for i in range(5):
        a, b = path[i], path[i + 1]
        out.append((a, max(a, b), min(a, b), b, vol))
    out[0] = (out[0][0], h, out[0][2], out[0][3], vol)
    out[-1] = (out[-1][0], out[-1][1], l, out[-1][3], vol)
    return out


SL_ABOVE = 1000.0   # planned SL above the week's close -> the loud red week closed below the zone


def _run(df, now=AFTER_CLOSE, sl=SL_ABOVE, zone_bottom=None):
    return rf.compute_red_vol_week(df, date(2026, 10, 23), now_et=now, sl=sl, zone_bottom=zone_bottom)


def test_clmt_like_red_week_waits():
    # real CLMT bars to Thu 2026-10-22 + a hypothetical Fri 10-23 close (the screenshot's red week)
    d = pd.read_csv(DATA / "red_vol_clmt_daily.csv.gz", index_col=0, parse_dates=True)
    d.loc[pd.Timestamp("2026-10-23")] = [49.3, 50.0, 48.5, 49.0, 2_000_000]
    out = _run(d)
    assert out["red_vol_week_date"] == "2026-10-23"
    assert out["f_no_red_vol_week"] is False
    assert out["red_vol_body_pct"] >= 50 and out["red_vol_ratio"] > 1
    assert out["red_vol_detail"].startswith("red high-volume last week, closed below the zone")
    assert out["red_vol_loud"] is True and out["red_vol_held"] is False and out["red_vol_close"] == 49.0


def test_week_not_complete_before_friday_1630():
    d = _daily(_week(100, 90, 100.5, 89.5, 3_000_000))
    assert _run(d, BEFORE_1630)["red_vol_week_date"] == "2026-10-16"   # still the previous (flat) week
    assert _run(d, BEFORE_1630)["f_no_red_vol_week"] is True
    assert _run(d)["f_no_red_vol_week"] is False                       # after 16:30 NY the red week counts


def test_mid_week_partial_week_ignored():
    d = _daily(_week(100, 90, 100.5, 89.5, 3_000_000)[:3])  # Mon-Wed only
    out = rf.compute_red_vol_week(d, date(2026, 10, 21), now_et=pd.Timestamp("2026-10-21 20:00", tz="America/New_York"))
    assert out["red_vol_week_date"] == "2026-10-16" and out["f_no_red_vol_week"] is True


def test_small_body_red_passes():
    # red but body 4 of range 10 = 40% < 50%
    out = _run(_daily(_week(100, 96, 103, 93, 3_000_000)))
    assert out["red_vol_body_pct"] == pytest.approx(40.0) and out["f_no_red_vol_week"] is True


def test_red_on_below_average_volume_passes():
    out = _run(_daily(_week(100, 90, 100.5, 89.5, 900_000)))
    assert out["red_vol_ratio"] == pytest.approx(0.9) and out["f_no_red_vol_week"] is True


def test_green_week_passes():
    out = _run(_daily(_week(90, 100, 100.5, 89.5, 3_000_000)))
    assert out["f_no_red_vol_week"] is True and "green" in out["red_vol_detail"]


def test_volume_basis_is_30_trading_days_before_the_week():
    # 30 days before the week at 1M, older days at 10M: only the last 30 count -> 1.5M/day is above average
    d = _daily(_week(100, 90, 100.5, 89.5, 1_500_000))
    d.iloc[: len(d) - 5 - 30, d.columns.get_loc("Volume")] = 10_000_000
    assert _run(d)["red_vol_ratio"] == pytest.approx(1.5)
    old = rf.CONFIG["red_vol_avg_days"]
    try:
        rf.CONFIG["red_vol_avg_days"] = 60  # configurable window
        assert _run(d)["red_vol_ratio"] < 1 and _run(d)["f_no_red_vol_week"] is True
    finally:
        rf.CONFIG["red_vol_avg_days"] = old


def test_next_week_clears_block():
    # red loud week 10-16, then a green week 10-23 -> eligible again
    d = _daily([], weeks=12)
    d = d.iloc[:-5]
    red = _week(100, 90, 100.5, 89.5, 3_000_000)
    green = _week(90, 93, 93.5, 89.8, 1_000_000)
    idx = d.index.append(pd.bdate_range("2026-10-12", periods=5)).append(pd.bdate_range("2026-10-19", periods=5))
    d = pd.DataFrame(list(d.itertuples(index=False, name=None)) + red + green, index=idx, columns=d.columns)
    assert _run(d.loc[:"2026-10-16"], pd.Timestamp("2026-10-17 12:00", tz="America/New_York"))["f_no_red_vol_week"] is False
    assert _run(d)["f_no_red_vol_week"] is True


def test_red_week_blocks_pass_again():
    """Eyal 2026-11-09 (falling knife): a healthy red loud last week is a core FAIL gate again (it was info only
    2026-10-26 .. 2026-11-09)."""
    base = {"f_dollar_vol": True, "f_no_earnings_14d": True, "f_history": True, "f_rr": True, "f_from_above": True, "f_no_inv_hammer": True, "f_after_earnings_week": True, "f_technical": True}
    assert rf.finalize_status({**base, "f_no_red_vol_week": True})["status"] == "PASS"
    r = rf.finalize_status({**base, "f_no_red_vol_week": False})
    assert r["status"] == "FAIL" and r["failed_filters"] == "no_red_vol_week"
    assert rf.finalize_status({**base, "f_rr": False, "f_no_red_vol_week": False})["status"] == "FAIL"


def test_zone_held_does_not_block_2026_11_16():
    """Eyal 2026-11-16: no separate falling-knife criterion; the loud red week blocks only when it closed below the
    planned SL. Close 90 >= SL 88 -> the zone held -> legitimate; SL 92 -> broke -> blocks."""
    d = _daily(_week(100, 90, 100.5, 89.5, 3_000_000))
    held = _run(d, sl=88.0)
    assert held["red_vol_loud"] is True and held["red_vol_held"] is True and held["f_no_red_vol_week"] is True
    assert "the zone held" in held["red_vol_detail"]
    broke = _run(d, sl=92.0)
    assert broke["red_vol_held"] is False and broke["f_no_red_vol_week"] is False
    assert "closed below the zone" in broke["red_vol_detail"]
    # no Long: the zone bottom is the level; no zone at all -> nothing to break
    assert _run(d, sl=None, zone_bottom=91.0)["f_no_red_vol_week"] is False
    assert _run(d, sl=None, zone_bottom=89.0)["f_no_red_vol_week"] is True
    none = _run(d, sl=None)
    assert none["f_no_red_vol_week"] is True and none["red_vol_loud"] is True and none["red_vol_held"] is None


def test_compute_row_uses_the_drawing_sl():
    """The report row checks the loud red week against its own Long (tv_sl)."""
    d = _daily(_week(100, 90, 100.5, 89.5, 3_000_000))
    rec = {"found": True, "zone_top": 95.0, "zone_bottom": 93.0, "entry": 95.0, "sl": 89.0, "tp": 110.0, "rr": 2.5,
           "read_date": "2026-10-23"}
    r = rf.compute_row("TST", d, date(2026, 10, 23), tv_rec=rec)
    assert r["red_vol_loud"] is True and r["f_no_red_vol_week"] is True        # close 90 >= SL 89: held
    r2 = rf.compute_row("TST", d, date(2026, 10, 23), tv_rec={**rec, "sl": 91.0})
    assert r2["f_no_red_vol_week"] is False                                       # close 90 < SL 91: broke
