"""f_no_inv_hammer (Eyal 2026-10-24, app command 9, BFH): the last COMPLETED weekly candle is an inverted
hammer -> a bearish sign. Since 2026-10-26 (WAIT cancelled) information only: the stock stays PASS."""
from datetime import date
from pathlib import Path

import pandas as pd

import report_filters as rf

DATA = Path(__file__).parent / "data"
AFTER_CLOSE = pd.Timestamp("2026-10-23 17:00", tz="America/New_York")
BEFORE_1630 = pd.Timestamp("2026-10-23 16:15", tz="America/New_York")


def _bfh():
    return pd.read_csv(DATA / "inv_hammer_bfh_daily.csv.gz", index_col=0, parse_dates=True)


def test_bfh_week_2026_10_23_is_inverted_hammer():
    # O 102.20 H 109.43 L 98.68 C 99.89: upper shadow 67%, body 21%, lower shadow 11% of the range
    out = rf.compute_inv_hammer_week(_bfh(), date(2026, 10, 23), now_et=AFTER_CLOSE)
    assert out["inv_hammer_week_date"] == "2026-10-23"
    assert out["f_no_inv_hammer"] is False
    assert out["inv_hammer_detail"].startswith("info (not a gate)")


def test_bfh_before_friday_1630_uses_previous_week():
    out = rf.compute_inv_hammer_week(_bfh(), date(2026, 10, 23), now_et=BEFORE_1630)
    assert out["inv_hammer_week_date"] == "2026-10-16" and out["f_no_inv_hammer"] is True


def test_shapes():
    assert rf.is_inverted_hammer(100, 110, 99.5, 101)        # classic, green
    assert rf.is_inverted_hammer(101, 110, 99.5, 100)        # classic, red
    assert not rf.is_inverted_hammer(100, 110, 96, 101)      # long lower shadow (40%)
    assert not rf.is_inverted_hammer(100, 104, 99.5, 103)    # big body, short upper shadow
    assert not rf.is_inverted_hammer(108, 110, 99.5, 109)    # body in the upper third (hammer-like / no)
    assert not rf.is_inverted_hammer(100, 100, 100, 100)     # no range
    # tiny doji with an ATR far larger than the range is not a real candle
    assert not rf.is_inverted_hammer(100, 100.5, 99.98, 100.01, atr=10.0)


def test_inverted_hammer_no_longer_blocks_pass():
    """Regression (Eyal 2026-10-26): a former WAIT (BFH-type inverted hammer) is PASS when the other gates pass."""
    base = {"f_dollar_vol": True, "f_no_earnings_14d": True, "f_history": True, "f_rr": True,
            "f_no_red_vol_week": True, "f_from_above": True}
    assert rf.finalize_status({**base, "f_no_inv_hammer": True})["status"] == "PASS"
    r = rf.finalize_status({**base, "f_no_inv_hammer": False})
    assert r["status"] == "PASS" and r["failed_filters"] == ""
    assert rf.finalize_status({**base, "f_no_inv_hammer": False, "f_no_red_vol_week": False})["status"] == "PASS"
    assert "f_no_inv_hammer" not in rf.CORE_FILTERS and "f_no_inv_hammer" in rf.WARN_FILTERS
    assert rf.finalize_status({**base, "f_no_inv_hammer": False, "f_rr": False})["status"] == "FAIL"
