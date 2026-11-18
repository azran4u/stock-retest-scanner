"""Regression for the 2026-11-18 stall: nightly 11-17 sat 7+ h in one ticker's earnings lookup (750/913) although it
was thread-bounded. Lookups now run in a killed-on-timeout child process with a pass budget + breaker and fall back
to the cached date / unknown."""
import ctypes
import json
import time
from datetime import date

import stock_screen as ss

TODAY = date(2026, 11, 18)


def _gil_hold(sec):
    # libc sleep through PyDLL keeps the GIL: a thread bound (join timeout) cannot return during it
    ctypes.PyDLL(None).sleep(int(sec))
    return "done"


def test_proc_bound_kills_gil_holder():
    t0 = time.monotonic()
    try:
        ss._proc_bounded_call(_gil_hold, 1.0, 30)
        raise AssertionError("no timeout")
    except TimeoutError:
        pass
    assert time.monotonic() - t0 < 8


def test_proc_bound_returns_and_reraises():
    assert ss._proc_bounded_call(lambda a, b=0: a + b, 10, 2, b=3) == 5
    try:
        ss._proc_bounded_call(lambda: 1 / 0, 10)
        raise AssertionError
    except ZeroDivisionError:
        pass


def test_lookup_many_hang_falls_back_to_cache_and_breaker(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "CACHE_DIR", tmp_path)
    (tmp_path / "earn_AAA.json").write_text(json.dumps({"earnings_date": "2026-11-25", "source": "tradingview",
                                                        "fetched_at": "2026-11-01T00:00:00Z"}))

    def fake(t, today=None):
        if t in ("AAA", "BBB", "CCC"):
            _gil_hold(30)
        return {"earnings_date": "2026-12-01", "days_to_earnings": 13, "earnings_known": True,
                "earnings_blackout": False, "earnings_source": "tradingview", "earnings_cache": "fetched"}

    monkeypatch.setattr(ss, "get_next_earnings", fake)
    t0 = time.monotonic()
    out = ss.earnings_lookup_many(["AAA", "BBB", "OK1", "CCC", "DDD"], TODAY, budget_s=60, per_ticker_s=1,
                                  breaker=1)
    assert time.monotonic() - t0 < 20
    assert out["AAA"]["earnings_date"] == "2026-11-25" and out["AAA"]["earnings_known"]   # cached date kept
    assert out["BBB"]["earnings_known"] is False                                        # unknown
    # breaker (1 timeout in a row) -> OK1 never asked, cache-only from then on
    assert out["OK1"]["earnings_cache"] == "fallback" and "skipped" in out["OK1"]["earnings_error"]


def test_lookup_many_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ss, "get_next_earnings", lambda t, today=None: (_gil_hold(30), {})[1])
    t0 = time.monotonic()
    out = ss.earnings_lookup_many([f"T{i}" for i in range(20)], TODAY, budget_s=3, per_ticker_s=2, breaker=99)
    assert time.monotonic() - t0 < 12
    assert all(not v["earnings_known"] for v in out.values()) and len(out) == 20
