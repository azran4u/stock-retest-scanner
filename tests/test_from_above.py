"""f_from_above (Eyal 2026-10-24, USB command 8): a stock that comes back to its zone from BELOW must first break the
zone (weekly close above the top) and come back from above; otherwise it is not interesting (not PASS)."""
from datetime import date
from pathlib import Path

import pandas as pd

import report_filters as rf

DATA = Path(__file__).parent / "data"
NOW = pd.Timestamp("2026-10-24 12:00", tz="America/New_York")


def _usb():
    return pd.read_csv(DATA / "from_above_usb_daily.csv.gz", index_col="date", parse_dates=True)


def _row(zb, zt, atr=2.5767):
    return {"tv_found": "yes", "tv_zone_bottom": zb, "tv_zone_top": zt, "weekly_atr": atr}


def test_usb_back_in_zone_from_below_fails():
    # weekly closes 57.51 / 57.08 / 58.73 under his 59.31-59.96 zone, then 59.58 back inside: from below
    out = rf.compute_from_above(_usb(), date(2026, 10, 23), _row(59.31, 59.96), now_et=NOW)
    assert out["f_from_above"] is False
    assert out["from_above_side"] == "below" and out["from_above_date"] == "2026-10-09"
    # (58.73 on 2026-10-16 is 0.22 ATR under the bottom = within the 0.25 ATR tolerance; 57.08 on 10-09 is not)


def test_usb_earlier_week_was_a_pullback_from_above():
    # as of 2026-09-18 (close 59.50 inside, 62.26 above the week before) the zone was approached from above
    out = rf.compute_from_above(_usb().loc[:"2026-09-18"], date(2026, 9, 18), _row(59.31, 59.96),
                                now_et=pd.Timestamp("2026-09-19 12:00", tz="America/New_York"))
    assert out["f_from_above"] is True and out["from_above_side"] == "above"


def test_pullback_in_progress_under_zone_is_not_from_below():
    # trailing closes under the zone after coming from above = a retest in progress (QCOM 2026-10-22)
    side, _ = rf.zone_approach([184.87, 175.5, 172.11, 172.83], range(4), 176.95, 180.62)
    assert side == "above"


def test_marginal_close_under_zone_within_tolerance():
    # OXY 2026-09-25: 56.86 vs bottom 57.04 = 0.07 ATR -> not 'under the zone'
    side, _ = rf.zone_approach([58.84, 56.86, 58.10], range(3), 57.04, 58.72, tol=0.25 * 2.5)
    assert side == "above"
    side, _ = rf.zone_approach([58.84, 56.86, 58.10], range(3), 57.04, 58.72, tol=0.0)
    assert side == "below"


def test_break_above_then_retest_clears():
    side, _ = rf.zone_approach([57.0, 59.5, 61.0, 59.6], range(4), 59.31, 59.96)
    assert side == "above"


def test_no_zone_never_blocks():
    out = rf.compute_from_above(_usb(), date(2026, 10, 23), {"tv_found": "no"}, now_et=NOW)
    assert out["f_from_above"] is True


def test_status_fails_from_below():
    base = {"f_dollar_vol": True, "f_no_earnings_14d": True, "f_history": True, "f_rr": True, "f_no_red_vol_week": True, "f_no_inv_hammer": True}
    assert rf.finalize_status({**base, "f_from_above": True})["status"] == "PASS"
    assert rf.finalize_status({**base, "f_from_above": False})["status"] == "FAIL"
    assert rf.finalize_status({**base, "f_from_above": False, "f_no_red_vol_week": False})["status"] == "FAIL"


def test_bot_approach_mirror_matches():
    from srs_app import bot_drawings as B
    for cl, zb, zt, tol in (([57.51, 57.08, 58.73, 59.58], 59.31, 59.96, 0.64), ([184.87, 175.5, 172.11, 172.83], 176.95, 180.62, 0.0),
                            ([58.84, 56.86, 58.10], 57.04, 58.72, 0.62), ([57.0, 59.5, 61.0, 59.6], 59.31, 59.96, 0.0)):
        assert B._approach(cl, zb, zt, tol) == rf.zone_approach(cl, range(len(cl)), zb, zt, tol=tol)[0]


def test_bot_obsolete_flags_from_below():
    from srs_app import bot_drawings as B
    bots = [{"kind": "zone", "zone_bottom": 44.34, "zone_top": 45.63, "created_at": "2026-10-23"},
            {"kind": "long", "entry": 45.4, "stop": 41.0, "target": 52.0, "created_at": "2026-10-23"}]
    fl = B.bot_obsolete("IRDM", bots, "2026-10-24", low_fn=lambda t, s: 44.0, price_fn=lambda t: (45.0, 2.0),
                        approach_fn=lambda t, zb, zt: "below")
    assert fl == ["from below"]
    fl = B.bot_obsolete("IRDM", bots, "2026-10-24", low_fn=lambda t, s: 44.0, price_fn=lambda t: (45.0, 2.0),
                        approach_fn=lambda t, zb, zt: "above")
    assert fl == []
