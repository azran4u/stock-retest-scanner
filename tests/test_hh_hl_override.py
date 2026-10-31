"""Eyal 2026-10-31 (SQM): after a head-and-shoulders neckline break, 'not technical' holds until the weekly
bars form a higher low and a higher high again ("until_hh_hl" override)."""
from datetime import date

import pandas as pd

import report_filters as rf


def _w(rows, start="2026-10-16"):
    idx = pd.date_range(start, periods=len(rows), freq="W-FRI")
    return pd.DataFrame(rows, columns=["h", "l", "c"], index=idx)


DOWN = [(63, 60, 60), (61, 56, 57), (61, 54, 55), (56, 50, 51)]


def test_still_falling_is_not_recovered():
    assert rf.hh_hl_recovered(_w(DOWN), "2026-10-16") is False


def test_bounce_without_higher_high_is_not_recovered():
    rows = DOWN + [(55, 51, 54), (57, 53, 56), (56, 52, 53), (56, 53, 55)]
    assert rf.hh_hl_recovered(_w(rows), "2026-10-16") is False


def test_higher_low_then_close_above_swing_high_recovers():
    rows = DOWN + [(55, 51, 54), (57, 53, 56), (56, 52, 53), (59, 54, 58)]
    assert rf.hh_hl_recovered(_w(rows), "2026-10-16") is True


def test_new_lower_low_resets():
    rows = DOWN + [(55, 51, 54), (57, 53, 56), (56, 49, 50), (58, 50, 57.5)]
    assert rf.hh_hl_recovered(_w(rows), "2026-10-16") is False


def test_override_holds_past_a_week_until_recovery(monkeypatch):
    monkeypatch.setattr(rf, "load_user_overrides",
                        lambda: {"XYZ": {"technical": False, "date": "2026-10-31", "since": "2026-10-16", "until_hh_hl": True}})
    rf._HH_HL_MEMO.clear()
    monkeypatch.setattr(rf, "_weekly_for", lambda t, hist=None: _w(DOWN + [(55, 51, 54), (57, 53, 56)]))
    r = rf.apply_user_overrides({"f_technical": True}, "XYZ", date(2026, 12, 20))
    assert r["f_technical"] is False and r["tech_override"]
    rf._HH_HL_MEMO.clear()
    monkeypatch.setattr(rf, "_weekly_for", lambda t, hist=None: _w(DOWN + [(55, 51, 54), (57, 53, 56), (56, 52, 53), (59, 54, 58)]))
    r = rf.apply_user_overrides({"f_technical": True}, "XYZ", date(2026, 12, 20))
    assert r["f_technical"] is True and r["tech_override"] == ""
    rf._HH_HL_MEMO.clear()


def test_sqm_real_candles_not_recovered_yet():
    w = rf._weekly_for("SQM")
    assert w is not None and rf.hh_hl_recovered(w, "2026-10-16", date(2026, 10, 31)) is False
