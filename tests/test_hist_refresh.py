"""Daily history cache refresh (BNY weekly volume vs TradingView, 2026-10-23).

The cache used to be append-only: a preliminary / partial Yahoo bar stayed frozen forever
(BNY 2026-10-09 vol 123,901 vs final 2,884,200; week of 2026-09-28 summed to 14.2M vs 20.8M).
"""
import datetime as dt

import pandas as pd

import stock_screen as ss


def _bars(days, vols, close=10.0):
    idx = pd.to_datetime(days)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close,
                         "Volume": [float(v) for v in vols]}, index=idx)


def test_merge_refresh_overwrites_preliminary_volume():
    old = _bars(["2026-10-07", "2026-10-08", "2026-10-09"], [1515682, 3435462, 123901])
    new = _bars(["2026-10-08", "2026-10-09", "2026-10-12"], [3447600, 2884200, 1911100])
    out = ss.merge_refresh(old, new, pd.Timestamp("2026-10-12"))
    assert list(out["Volume"]) == [1515682, 3447600, 2884200, 1911100]
    assert out.index.is_unique and out.index.is_monotonic_increasing


def test_merge_refresh_drops_unfinished_session_and_keeps_old_on_empty():
    old = _bars(["2026-10-08", "2026-10-09"], [1, 2])
    new = _bars(["2026-10-09", "2026-10-12"], [3, 4])
    out = ss.merge_refresh(old, new, pd.Timestamp("2026-10-09"))
    assert list(out.index.strftime("%Y-%m-%d")) == ["2026-10-08", "2026-10-09"] and out["Volume"].iloc[-1] == 3
    assert ss.merge_refresh(old, pd.DataFrame(), pd.Timestamp("2026-10-09")) is old


def test_last_session_waits_for_close():
    fri = dt.date(2026, 10, 9)
    assert ss.last_us_session_date(dt.datetime(2026, 10, 9, 11, 0)).date() == dt.date(2026, 10, 8)  # mid-session
    assert ss.last_us_session_date(dt.datetime(2026, 10, 9, 17, 0)).date() == fri
    assert ss.last_us_session_date(dt.datetime(2026, 10, 10, 1, 49)).date() == fri  # Sat night run
    assert ss.last_us_session_date(dt.datetime(2026, 10, 12, 9, 0)).date() == fri  # Mon pre-open
    assert ss.last_us_session_date(fri).date() == fri


def test_refresh_refetches_overlap_window(monkeypatch):
    calls = []

    def fake_download(group, chunk=50, start=None, end=None, period="5y"):
        calls.append((tuple(group), start, end))
        return {t: _bars(["2026-10-08", "2026-10-09"], [3447600, 2884200]) for t in group}

    monkeypatch.setattr(ss, "download_batch", fake_download)
    monkeypatch.setattr(ss, "last_us_session_date", lambda now=None: pd.Timestamp("2026-10-09"))
    hist = {"BNY": _bars(["2026-10-07", "2026-10-08", "2026-10-09"], [1515682, 3435462, 123901])}
    out = ss.refresh_hist_map(hist, ["BNY"], overlap_days=14)
    assert calls == [(("BNY",), "2026-09-25", "2026-10-10")]  # up to date, still re-fetched
    assert list(out["BNY"]["Volume"]) == [1515682, 3447600, 2884200]
