"""Earnings date cache (CXW 2026-10-23): cached future dates are re-fetched, sources are combined and the
EARLIEST plausible upcoming date wins (conservative for the 14-day no-earnings gate)."""
import json
from datetime import date, datetime, timezone

import pytest

import stock_screen as ss

TODAY = date(2026, 10, 23)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ss, "resolve_exchange", lambda t: "NYSE")
    calls = {"tv": 0, "yf": 0}
    answers = {"tv": None, "yf": None, "nasdaq": (None, False)}
    monkeypatch.setattr(ss, "nasdaq_earnings_date", lambda t: answers["nasdaq"])

    def tv(t, exchange=None):
        calls["tv"] += 1
        return answers["tv"]

    def yf(t, today):
        calls["yf"] += 1
        return answers["yf"], ("get_earnings_dates" if answers["yf"] else "unknown"), []

    monkeypatch.setattr(ss, "scrape_tradingview_earnings_date", tv)
    monkeypatch.setattr(ss, "_yahoo_next_earnings", yf)
    return tmp_path, calls, answers


def _cache(dirp, ticker, ed, fetched_at, source="tradingview"):
    (dirp / f"earn_{ticker}.json").write_text(json.dumps({"earnings_date": ed, "source": source, "fetched_at": fetched_at}))


def _hours_ago(h):
    return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - h * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_cxw_projected_date_cached_weeks_ago_is_refetched(env):
    d, calls, ans = env
    # 2026-09-29 TradingView answer (projected 11-09); company confirmed 11-04 on 10-05
    _cache(d, "CXW", "2026-11-09", "2026-09-29T09:55:30Z")
    assert ss.earn_cache_lookup("CXW", TODAY)[0] == "stale"
    ans["tv"], ans["yf"] = date(2026, 11, 4), date(2026, 11, 4)
    out = ss.get_next_earnings("CXW", today=TODAY)
    assert out["earnings_date"] == "2026-11-04" and out["days_to_earnings"] == 12 and out["earnings_blackout"]
    saved = json.loads((d / "earn_CXW.json").read_text())
    assert saved["earnings_date"] == "2026-11-04" and saved["sources"]["tradingview"] == "2026-11-04"


def test_sources_disagree_earliest_wins(env):
    d, calls, ans = env
    ans["tv"], ans["yf"] = date(2026, 11, 9), date(2026, 11, 4)   # TV projected, Yahoo confirmed
    out = ss.get_next_earnings("XYZ", today=TODAY)
    assert out["earnings_date"] == "2026-11-04" and out["earnings_source"] == "get_earnings_dates"
    assert calls == {"tv": 1, "yf": 1}


def test_pick_ignores_past_and_implausible_dates():
    pick = ss.pick_earnings_date
    assert pick({"tradingview": date(2026, 10, 1), "calendar": date(2026, 11, 4)}, TODAY) == (date(2026, 11, 4), "calendar")
    assert pick({"tradingview": date(2027, 9, 1), "calendar": date(2026, 11, 20)}, TODAY)[0] == date(2026, 11, 20)
    assert pick({"tradingview": date(2027, 9, 1)}, TODAY) == (None, "unknown")         # > 190 days ahead
    assert pick({"tradingview": date(2027, 3, 4)}, TODAY)[0] == date(2027, 3, 4)       # semiannual reporter ok
    assert pick({"tradingview": date(2026, 11, 4), "get_earnings_dates": date(2026, 11, 4)}, TODAY) == \
        (date(2026, 11, 4), "get_earnings_dates+tradingview")
    assert pick({"tradingview": TODAY}, TODAY) == (TODAY, "tradingview")  # earnings today counts


def test_fresh_cache_hit_no_network(env):
    d, calls, ans = env
    _cache(d, "AAA", "2027-01-20", _hours_ago(24))       # far date, fetched 1 day ago (< 4 days)
    assert ss.earn_cache_lookup("AAA", TODAY)[0] == "hit"
    assert ss.get_next_earnings("AAA", today=TODAY)["earnings_date"] == "2027-01-20"
    assert calls == {"tv": 0, "yf": 0}


def test_far_date_refreshed_after_refresh_days(env):
    d, _, _ = env
    _cache(d, "AAA", "2027-01-20", _hours_ago(ss.EARN_REFRESH_DAYS * 24 + 1))
    assert ss.earn_cache_lookup("AAA", TODAY)[0] == "stale"


def test_near_date_refreshed_daily(env):
    d, _, _ = env
    _cache(d, "BBB", "2026-11-15", _hours_ago(ss.EARN_NEAR_REFRESH_HOURS + 1))   # within 30 days
    assert ss.earn_cache_lookup("BBB", TODAY)[0] == "stale"
    _cache(d, "BBB", "2026-11-15", _hours_ago(2))
    assert ss.earn_cache_lookup("BBB", TODAY)[0] == "hit"


def test_stale_kept_when_every_source_fails(env):
    d, calls, ans = env
    _cache(d, "CCC", "2026-11-30", "2026-09-29T09:55:30Z")
    out = ss.get_next_earnings("CCC", today=TODAY)
    assert out["earnings_date"] == "2026-11-30" and out["earnings_cache"] == "stale"
    assert calls == {"tv": 1, "yf": 1}


def test_past_cached_date_refetched_and_miss_cached(env):
    d, calls, ans = env
    _cache(d, "DDD", "2026-10-01", "2026-09-01T00:00:00Z")
    assert ss.earn_cache_lookup("DDD", TODAY)[0] == "fetch"
    out = ss.get_next_earnings("DDD", today=TODAY)
    assert out["earnings_known"] is False
    assert ss.earn_cache_lookup("DDD", TODAY)[0] == "recent_miss"


def test_confirmed_date_wins_over_earlier_estimate(env):
    d, calls, ans = env
    # Yahoo's algorithmic estimate is earlier, Nasdaq says the company confirmed a later date
    ans["tv"], ans["yf"], ans["nasdaq"] = date(2026, 11, 18), date(2026, 11, 5), (date(2026, 11, 18), True)
    out = ss.get_next_earnings("CNF", today=TODAY)
    assert out["earnings_date"] == "2026-11-18" and "confirmed" in out["earnings_source"]
    saved = json.loads((d / "earn_CNF.json").read_text())
    assert saved["sources"]["confirmed"] == "nasdaq" and saved["sources"]["get_earnings_dates"] == "2026-11-05"


def test_unconfirmed_nasdaq_is_just_another_estimate(env):
    d, calls, ans = env
    ans["tv"], ans["yf"], ans["nasdaq"] = date(2026, 11, 25), None, (date(2026, 11, 18), False)
    assert ss.get_next_earnings("EST", today=TODAY)["earnings_date"] == "2026-11-18"


def test_parse_nasdaq_texts():
    conf = {"announcement": "Earnings announcement* for CXW: Nov 04, 2026",
            "reportText": "CoreCivic, Inc. Common Stock is expected* to report earnings on  11/04/2026 after market close."}
    est = {"announcement": "Earnings announcement* for NVDA: Nov 18, 2026",
           "reportText": "NVIDIA Corporation Common Stock is estimated to report earnings on  11/18/2026. The upcoming "
                         "earnings date is derived from an algorithm based on a company's historical reporting dates."}
    none = {"announcement": "Earnings announcement* for TSM: ", "reportText": "Our vendor ... hasn't provided us ..."}
    assert ss.parse_nasdaq_earnings(conf) == (date(2026, 11, 4), True)
    assert ss.parse_nasdaq_earnings(est) == (date(2026, 11, 18), False)
    assert ss.parse_nasdaq_earnings(none) == (None, False)
