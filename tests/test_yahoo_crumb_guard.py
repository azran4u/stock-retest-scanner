"""Regression for the 2026-10-30 nightly: the export stalled after Yahoo answered HTTP 429 on the crumb and then
401 'Invalid Crumb' / 'User is unable to access this feature' to every earnings call. yfinance only LOGS those errors
and returns an empty answer, so nothing counted as a failure. Now the run-level guard (stock_screen.YAHOO_EARN_GUARD)
sees the logged auth errors, stops asking Yahoo after a few, caps the total Yahoo time, and the dates fall back to
the cached / TradingView / Nasdaq dates (earn_{T}.json) without overwriting good cached data."""
import json
import logging
import sys
import threading
import time
import types
from datetime import date

import pytest

import stock_screen as ss

YLOG = logging.getLogger("yfinance")


@pytest.fixture
def env(tmp_path, monkeypatch):
    import report_filters as rf
    monkeypatch.setattr(ss, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(rf, "FV_CACHE_DIR", tmp_path)
    monkeypatch.setattr(rf, "_EARN_HIST_TIMEOUTS", [0])
    monkeypatch.setattr(ss, "is_fund", lambda t: False)
    calls = {"n": 0}

    class CrumbFail:  # what yfinance 1.7 does on 401 / 429: log the error, return nothing
        def __init__(self, t):
            calls["n"] += 1

        def get_earnings_dates(self, limit=16):
            YLOG.error('HTTP Error 401: {"finance":{"result":null,"error":{"code":"Unauthorized","description":"Invalid Crumb"}}}')
            return None

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=CrumbFail))
    return tmp_path, rf, calls


def test_logged_401_falls_back_and_breaker_stops_yahoo(env):
    d, rf, calls = env
    # TradingView / Nasdaq answers stored by the scanner, and an expired but good earnhist cache
    (d / "earn_AAA.json").write_text(json.dumps({"earnings_date": "2026-11-12", "last_earnings_date": "2026-08-06",
                                                 "sources": {"tradingview": "2026-11-12", "nasdaq": "2026-11-12"}}))
    old = {"fetched_at": "2026-08-01 00:00:00", "dates": ["2026-02-05", "2026-05-07"], "note": ""}
    (d / "earnhist_AAA.json").write_text(json.dumps(old))
    dates, note = rf.earnings_history("AAA")
    assert calls["n"] == 1  # an auth error is not retried
    assert dates == ["2026-02-05", "2026-05-07", "2026-08-06", "2026-11-12"]
    assert "fallback" in note and "auth" in note.lower()
    assert json.loads((d / "earnhist_AAA.json").read_text()) == old  # good older cache kept, failure not cached

    for i in range(10):
        rf.earnings_history(f"T{i}")
    breaker = ss.YAHOO_EARN_GUARD.breaker
    assert calls["n"] == breaker  # after BREAKER failures in a row Yahoo is not asked again this run
    assert ss.YAHOO_EARN_GUARD.tripped and "in a row" in ss.YAHOO_EARN_GUARD.tripped
    t0 = time.monotonic()
    dates, note = rf.earnings_history("AAA")
    assert time.monotonic() - t0 < 0.1 and calls["n"] == breaker and dates and "skipped" in note
    assert not any((d / f"earnhist_T{i}.json").exists() for i in range(10))  # nothing cached: next run retries


def test_time_budget_caps_the_whole_run(env, monkeypatch):
    d, rf, calls = env
    slow = threading.Event()

    class Slow:
        def __init__(self, t):
            calls["n"] += 1

        def get_earnings_dates(self, limit=16):
            slow.wait(0.4)
            return None  # an empty answer, no error (does not trip the breaker)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Slow))
    monkeypatch.setattr(ss.YAHOO_EARN_GUARD, "budget_s", 1.0)
    t0 = time.monotonic()
    for i in range(20):
        rf.earnings_history(f"S{i}")
    assert time.monotonic() - t0 < 2.5 and calls["n"] <= 4
    assert "budget" in (ss.YAHOO_EARN_GUARD.tripped or "")


def test_raised_rate_limit_counts_too(env, monkeypatch):
    d, rf, calls = env

    class Raises:
        def __init__(self, t):
            calls["n"] += 1

        def get_earnings_dates(self, limit=16):
            raise RuntimeError("Too Many Requests. Rate limited. Try after a while.")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Raises))
    for i in range(8):
        rf.earnings_history(f"R{i}")
    assert calls["n"] == ss.YAHOO_EARN_GUARD.breaker


def test_earnings_marks_use_cache_when_yahoo_refuses(env):
    d, rf, calls = env
    from srs_app import earnings_marks as em
    (d / "earn_BBB.json").write_text(json.dumps({"earnings_date": "2026-11-20", "last_earnings_date": "2026-08-14"}))
    (d / "earnhist_BBB.json").write_text(json.dumps({"fetched_at": "2026-10-01 00:00:00", "dates": ["2026-05-15", "2026-08-14"]}))
    out = em.ticker_marks("BBB", date(2026, 10, 30), d, next_date="2026-11-20",
                          fetch=lambda t: sys.modules["yfinance"].Ticker(t).get_earnings_dates(),
                          bounded=ss.YAHOO_EARN_GUARD.call)
    assert out["src"] == "cache" and [p["d"] for p in out["p"]] == ["2026-05-15", "2026-08-14"] and out["n"] == "2026-11-20"
    assert not (d / "earnmarks_BBB.json").exists()  # a refusal is not cached as 'no data'


def test_ok_answer_resets_the_breaker(env, monkeypatch):
    d, rf, calls = env
    import pandas as pd

    class Ok:
        def __init__(self, t):
            calls["n"] += 1

        def get_earnings_dates(self, limit=16):
            return pd.DataFrame({"EPS Estimate": [1.0]}, index=pd.DatetimeIndex(["2026-08-06"]))

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ok))
    dates, note = rf.earnings_history("OK1")
    assert dates == ["2026-08-06"] and note == "" and ss.YAHOO_EARN_GUARD.consecutive == 0
    assert json.loads((d / "earnhist_OK1.json").read_text())["dates"] == ["2026-08-06"]
