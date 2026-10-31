"""f_after_earnings_week (Eyal 2026-10-31, app command 12, CHRW): a stock whose last completed weekly candle is an
earnings week cannot be PASS (volume and price move are driven by the report); wait for the close of the FOLLOWING
week, then the rules decide again."""
from datetime import date
from pathlib import Path

import pandas as pd

import report_filters as rf

DATA = Path(__file__).parent / "data"
SAT = pd.Timestamp("2026-10-31 12:00", tz="America/New_York")


def _chrw():
    return pd.read_csv(DATA / "earnings_week_chrw_daily.csv.gz", index_col=0, parse_dates=True)


def _upto(df, d):
    return df[df.index <= pd.Timestamp(d)]


def test_chrw_earnings_week_2026_10_30_blocks():
    # CHRW reported Wed 2026-10-28 before the open (gap 143.59 -> 127.60); week ending 10-30 = earnings week
    out = rf.compute_earnings_week(_chrw(), date(2026, 10, 31), [("2026-10-28", "bmo")], "2027-01-27", now_et=SAT)
    assert out["earn_week_date"] == "2026-10-30"
    assert out["f_after_earnings_week"] is False
    assert out["earn_week_report"] == "2026-10-28"
    assert "2026-11-06" in out["earn_week_detail"]  # wait for the close of the following week


def test_cleared_after_the_following_week_closes():
    df = _chrw()
    nxt = pd.DataFrame({"Open": 125.0, "High": 127.0, "Low": 123.0, "Close": 126.0, "Volume": 2e6},
                       index=pd.bdate_range("2026-11-02", "2026-11-06"))
    df2 = pd.concat([df, nxt])
    fri = pd.Timestamp("2026-11-06 17:00", tz="America/New_York")
    out = rf.compute_earnings_week(df2, date(2026, 11, 6), [("2026-10-28", "bmo")], "2027-01-27", now_et=fri)
    assert out["earn_week_date"] == "2026-11-06" and out["f_after_earnings_week"] is True
    # mid-week (week not closed yet): still blocked
    wed = pd.Timestamp("2026-11-04 17:00", tz="America/New_York")
    out = rf.compute_earnings_week(_upto(df2, "2026-11-04"), date(2026, 11, 4), [("2026-10-28", "bmo")],
                                   now_et=wed)
    assert out["f_after_earnings_week"] is False


def test_report_in_running_week_blocks():
    # last completed week ends 10-23; report on Tue 10-27 (week still running) -> blocked already
    tue = pd.Timestamp("2026-10-27 17:00", tz="America/New_York")
    out = rf.compute_earnings_week(_upto(_chrw(), "2026-10-27"), date(2026, 10, 27), [("2026-10-27", "amc")],
                                   now_et=tue)
    assert out["earn_week_date"] == "2026-10-23" and out["f_after_earnings_week"] is False


def test_before_report_and_old_reports_pass():
    # week ending 10-23, report not yet out (future date) -> this gate passes (the 14-day gate handles it)
    fri = pd.Timestamp("2026-10-23 17:00", tz="America/New_York")
    out = rf.compute_earnings_week(_upto(_chrw(), "2026-10-23"), date(2026, 10, 23),
                                   [("2026-07-29", "amc"), ("2026-10-28", "bmo")], now_et=fri)
    assert out["f_after_earnings_week"] is True
    assert rf.compute_earnings_week(_chrw(), date(2026, 10, 31), [], None, now_et=SAT)["f_after_earnings_week"] is True


def test_friday_after_close_counts_for_next_week():
    # report Fri 10-23 after the close trades Mon 10-26 -> the week ending 10-30 is the earnings week
    out = rf.compute_earnings_week(_chrw(), date(2026, 10, 31), [("2026-10-23", "amc")], now_et=SAT)
    assert out["f_after_earnings_week"] is False
    # same date before the open -> traded in the week ending 10-23, already followed by a closed week
    out = rf.compute_earnings_week(_chrw(), date(2026, 10, 31), [("2026-10-23", "bmo")], now_et=SAT)
    assert out["f_after_earnings_week"] is True


def test_is_core_gate():
    assert "f_after_earnings_week" in rf.CORE_FILTERS
    base = {f: True for f in rf.CORE_FILTERS}
    assert rf.finalize_status(dict(base))["status"] == "PASS"
    r = rf.finalize_status({**base, "f_after_earnings_week": False})
    assert r["status"] == "FAIL" and r["failed_filters"] == "after_earnings_week"


def test_export_blocks_pass_row(monkeypatch):
    from srs_app import export_data as ed
    monkeypatch.setattr(rf, "cached_report_dates", lambda t: [("2026-10-28", "bmo")])
    rows = [{"ticker": "CHRW", "status": "PASS", "badges": ["pass", "position"], "earnings_date": "2027-01-27"}]
    n = ed.attach_earnings_week(rows, "2026-10-31", hist={"CHRW": _chrw()})
    assert n == 1 and rows[0]["status"] == "FAIL" and rows[0]["badges"] == ["position"]
    assert rows[0]["f_after_earnings_week"] is False and rows[0]["earn_week_report"] == "2026-10-28"
