"""Regression for the 2026-10-27 nightly stall: yfinance get_earnings_dates hung for hours (curl_cffi perform) on
ETFs that answer 404 'No fundamentals data found'. Every Yahoo lookup and every ticker's whole earnings lookup are
wall-clock bounded, funds skip Yahoo, negative answers are cached, and the 3-source rule still holds."""
import json
import logging
import sys
import threading
import time
import types
from datetime import date, datetime, timedelta, timezone

import pytest

import stock_screen as ss

TODAY = date(2026, 10, 28)
FOREVER = threading.Event()  # never set: a "hung" network call


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ss, "resolve_exchange", lambda t: "NASDAQ")
    monkeypatch.setattr(ss, "YAHOO_CALL_TIMEOUT_S", 0.5)
    ans = {"tv": None, "nasdaq": (None, False)}
    calls = {"yf": 0}
    monkeypatch.setattr(ss, "scrape_tradingview_earnings_date", lambda t, exchange=None: ans["tv"])
    monkeypatch.setattr(ss, "nasdaq_earnings_date", lambda t: ans["nasdaq"])
    return tmp_path, ans, calls


def _hang_yahoo(calls):
    def yf(t, today, past=None):
        calls["yf"] += 1
        FOREVER.wait(60)
        return None, "unknown", []
    return yf


def test_hanging_yahoo_returns_within_bound(env, monkeypatch):
    d, ans, calls = env
    monkeypatch.setattr(ss, "_yahoo_next_earnings", _hang_yahoo(calls))
    t0 = time.monotonic()
    out = ss.get_next_earnings("SCHF", today=TODAY)
    assert time.monotonic() - t0 < 3
    assert calls["yf"] == 1 and out["earnings_date"] is None and "timed out" in out["earnings_error"]
    # no date from TradingView, Yahoo or Nasdaq -> cached miss -> 'none' = passes the earnings gate
    assert ss.earnings_state("SCHF", TODAY)["kind"] == "none"


def test_hanging_yahoo_keeps_other_sources(env, monkeypatch):
    d, ans, calls = env
    monkeypatch.setattr(ss, "_yahoo_next_earnings", _hang_yahoo(calls))
    ans["tv"] = date(2026, 11, 5)
    t0 = time.monotonic()
    out = ss.get_next_earnings("XYZ", today=TODAY)
    assert time.monotonic() - t0 < 3
    assert out["earnings_date"] == "2026-11-05" and out["earnings_blackout"]


def test_real_yahoo_code_with_hanging_http_is_bounded(env, monkeypatch):
    """The real _yahoo_next_earnings with a fake yfinance whose earnings scrape never returns (curl perform hang)."""
    d, ans, calls = env

    class T:
        def __init__(self, t):
            self.t = t

        def get_earnings_dates(self, limit=12):
            FOREVER.wait(60)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    t0 = time.monotonic()
    out = ss.get_next_earnings("QQQ", today=TODAY)
    assert time.monotonic() - t0 < 3 and out["earnings_date"] is None


def test_yahoo_404_no_fundamentals_is_cached(env, monkeypatch):
    """yfinance only LOGS 'No fundamentals data found' (404) - it is captured and Yahoo is skipped for 30 days."""
    d, ans, calls = env

    class T:
        def __init__(self, t):
            self.t = t
            calls["yf"] += 1

        def get_earnings_dates(self, limit=12):
            logging.getLogger("yfinance").error(
                'HTTP Error 404: {"quoteSummary":{"result":null,"error":{"code":"Not Found","description":'
                f'"No fundamentals data found for symbol: {self.t}"}}}}')
            return None

        calendar = None
        earnings_dates = None

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    out = ss.get_next_earnings("PYLD", today=TODAY)
    assert out["earnings_date"] is None and calls["yf"] == 1
    saved = json.loads((d / "earn_PYLD.json").read_text())
    assert saved["source"] == "miss" and saved.get("yahoo_nofund_at")
    ss.get_next_earnings("PYLD", today=TODAY, force=True)   # re-check: TV / Nasdaq asked again, Yahoo not
    assert calls["yf"] == 1
    assert json.loads((d / "earn_PYLD.json").read_text()).get("yahoo_nofund_at") == saved["yahoo_nofund_at"]
    assert ss.earnings_state("PYLD", TODAY)["kind"] == "none"


def test_fund_skips_yahoo_and_miss_is_cached_30_days(env, monkeypatch):
    d, ans, calls = env
    monkeypatch.setattr(ss, "_yahoo_next_earnings", _hang_yahoo(calls))
    (d / "fund_types.json").write_text(json.dumps({"QQQ": {"type": "fund", "subtype": "etf",
                                                          "fetched": datetime.now(timezone.utc).isoformat()}}))
    assert ss.is_fund("QQQ")
    t0 = time.monotonic()
    out = ss.get_next_earnings("QQQ", today=TODAY)
    assert time.monotonic() - t0 < 0.5 and calls["yf"] == 0 and out["earnings_date"] is None
    saved = json.loads((d / "earn_QQQ.json").read_text())
    assert saved["fund"] is True and saved["source"] == "miss"
    # 3 days later it is still a cached miss (a stock's miss expires after 20 h)
    later = datetime.now(timezone.utc) + timedelta(days=3)
    assert ss.earn_cache_lookup("QQQ", TODAY, now=later)[0] == "recent_miss"
    assert ss.earn_cache_lookup("QQQ", TODAY, now=datetime.now(timezone.utc) + timedelta(days=31))[0] == "fetch"
    assert ss.earnings_state("QQQ", TODAY)["kind"] == "none"


def test_fund_with_a_date_still_counts(env, monkeypatch):
    """A fund is not exempt by type: a date from TradingView / Nasdaq still applies (3-source rule)."""
    d, ans, calls = env
    monkeypatch.setattr(ss, "_yahoo_next_earnings", _hang_yahoo(calls))
    (d / "yfown_PDI.json").write_text(json.dumps({"quote_type": "CLOSEDENDFUND"}))
    ans["nasdaq"] = (date(2026, 11, 3), True)
    out = ss.get_next_earnings("PDI", today=TODAY)
    assert calls["yf"] == 0 and out["earnings_date"] == "2026-11-03"


def test_prefetch_fund_types_parses_scanner(env):
    d, ans, calls = env
    rows = {"data": [{"s": "NASDAQ:QQQ", "d": ["QQQ", "fund", "etf", True]},
                     {"s": "NYSE:BRK.B", "d": ["BRK.B", "stock", "common", True]},
                     {"s": "NASDAQ:AAPL", "d": ["AAPL", "stock", "common", True]}]}
    cache = ss.prefetch_fund_types(["QQQ", "BRK-B", "AAPL", "NOPE"], post=lambda body: rows)
    assert cache["QQQ"]["type"] == "fund" and cache["BRK-B"]["type"] == "stock" and cache["NOPE"]["type"] is None
    assert ss.is_fund("QQQ") and not ss.is_fund("AAPL") and not ss.is_fund("NOPE")


def test_prefetch_fund_types_hanging_scanner_is_bounded(env, monkeypatch):
    d, ans, calls = env
    real = ss._bounded_call
    monkeypatch.setattr(ss, "_bounded_call", lambda fn, timeout_s, *a, **k: real(fn, 0.3, *a, **k))
    t0 = time.monotonic()
    cache = ss.prefetch_fund_types(["QQQ"], post=lambda body: FOREVER.wait(60))
    assert time.monotonic() - t0 < 2 and "QQQ" not in cache


def test_verify_loop_bounds_each_ticker(env, monkeypatch):
    d, ans, calls = env
    monkeypatch.setattr(ss, "EARN_TICKER_TIMEOUT_S", 0.3)
    monkeypatch.setattr(ss, "get_next_earnings", lambda t, today=None: FOREVER.wait(60))
    res = [{"ticker": t, "status": "PASS", "reason": "", "detail": {}} for t in ("AAA", "BBB")]
    t0 = time.monotonic()
    out = ss._enrich_verify_earnings(res)
    assert time.monotonic() - t0 < 2
    assert all(not v["earnings_known"] and "timed out" in v["earnings_error"] for v in out.values())


def test_earnings_history_hang_is_bounded_and_funds_skip(env, monkeypatch):
    """report_filters.earnings_history (hammer calm weeks) had the same unbounded yfinance scrape (export 2026-10-28)."""
    import report_filters as rf
    d, ans, calls = env
    monkeypatch.setattr(rf, "EARN_HIST_CALL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(rf, "_EARN_HIST_TIMEOUTS", [0])

    class T:
        def __init__(self, t):
            calls["yf"] += 1

        def get_earnings_dates(self, limit=16):
            FOREVER.wait(60)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    t0 = time.monotonic()
    dates, note = rf.earnings_history("XYZ")
    assert time.monotonic() - t0 < 2 and dates is None and "timed out" in note and calls["yf"] == 1
    (d / "fund_types.json").write_text(json.dumps({"QQQ": {"type": "fund", "fetched": datetime.now(timezone.utc).isoformat()}}))
    dates, note = rf.earnings_history("QQQ")
    assert calls["yf"] == 1 and dates is None and note == "fund: no earnings"
    assert json.loads((d / "earnhist_QQQ.json").read_text())["fund"] is True
    for t in ("A1", "A2"):
        rf.earnings_history(t)
    assert calls["yf"] == 3
    t0 = time.monotonic()
    dates, note = rf.earnings_history("A3")   # breaker open after 3 consecutive timeouts: no call
    assert calls["yf"] == 3 and "skipped" in note and time.monotonic() - t0 < 0.1
    assert not (d / "earnhist_A3.json").exists()
