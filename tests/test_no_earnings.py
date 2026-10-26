"""Eyal 2026-10-26: no earnings date in any of TradingView / Yahoo / Nasdaq -> assume no earnings (ETFs etc.), the
14-day must-have passes. A PAST report only (KN reported 10-22, next not out) = a company with earnings: next is
estimated as last + 91 days (flagged) and the 14-day rule applies to the estimate."""
import json
from datetime import date

import pandas as pd
import pytest

import report_filters as rf
import stock_screen as ss
import tv_drawings as tvd

TODAY = date(2026, 10, 26)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(rf, "FV_CACHE_DIR", tmp_path)
    monkeypatch.setattr(ss, "resolve_exchange", lambda t: "NYSE")
    ans = {"tv": None, "yf": None, "yf_past": [], "nasdaq": (None, False)}
    monkeypatch.setattr(ss, "scrape_tradingview_earnings_date", lambda t, exchange=None: ans["tv"])

    def yf(t, today, past=None):
        if past is not None:
            past.extend(ans["yf_past"])
        return ans["yf"], ("get_earnings_dates" if ans["yf"] else "unknown"), []
    monkeypatch.setattr(ss, "_yahoo_next_earnings", yf)
    monkeypatch.setattr(ss, "nasdaq_earnings_date", lambda t: ans["nasdaq"])
    return tmp_path, ans


def _row(t, kind, ed):
    return rf.compute_row(t, None, TODAY, None, ed, earnings_kind=kind)


def test_etf_no_dates_anywhere_passes(env):
    d, ans = env
    out = ss.get_next_earnings("SPY", today=TODAY, force=True)
    assert out["earnings_date"] is None
    st = ss.earnings_state("SPY", TODAY)
    assert st == {"kind": "none", "date": None, "last": None}
    r = _row("SPY", st["kind"], st["date"])
    assert r["f_no_earnings_14d"] is True and r["earnings_none"] is True and r["days_to_earnings"] is None
    st2 = rf.earn_state("SPY", TODAY)
    assert st2["kind"] == "none"


def test_never_looked_up_still_fails(env):
    st = ss.earnings_state("ZZZ", TODAY)
    assert st["kind"] == "unknown"
    assert _row("ZZZ", st["kind"], st["date"])["f_no_earnings_14d"] is False


def test_past_report_only_uses_estimate(env):
    d, ans = env
    ans["tv"] = date(2026, 10, 22)  # TradingView still shows the report that just happened (KN)
    ss.get_next_earnings("KN", today=TODAY, force=True)
    c = json.loads((d / "earn_KN.json").read_text())
    assert c["earnings_date"] is None and c["last_earnings_date"] == "2026-10-22"
    st = ss.earnings_state("KN", TODAY)
    assert st == {"kind": "estimated", "date": "2027-01-21", "last": "2026-10-22"}
    r = _row("KN", st["kind"], st["date"])
    assert r["earnings_estimated"] is True and r["earnings_none"] is False
    assert r["f_no_earnings_14d"] is True and r["days_to_earnings"] == 87


def test_past_cached_date_becomes_last(env):
    d, ans = env
    (d / "earn_KN.json").write_text(json.dumps({"earnings_date": "2026-10-22", "source": "tradingview", "fetched_at": "2026-09-20T07:39:42Z"}))
    st = ss.earnings_state("KN", TODAY)  # before the re-fetch: the cached date passed
    assert st["kind"] == "estimated" and st["last"] == "2026-10-22"
    ss.get_next_earnings("KN", today=TODAY)  # re-fetch finds nothing upcoming: the past date is kept as last
    c = json.loads((d / "earn_KN.json").read_text())
    assert c["source"] == "miss" and c["last_earnings_date"] == "2026-10-22"
    assert ss.earnings_state("KN", TODAY)["kind"] == "estimated"


def test_estimate_within_14d_fails(env):
    d, ans = env
    ans["yf_past"] = [date(2026, 7, 30)]  # + 91 = 2026-10-29 (3 days away)
    ss.get_next_earnings("ABC", today=TODAY, force=True)
    st = ss.earnings_state("ABC", TODAY)
    assert st["kind"] == "estimated" and st["date"] == "2026-10-29"
    r = _row("ABC", st["kind"], st["date"])
    assert r["f_no_earnings_14d"] is False and r["earnings_blackout"] is True


def test_known_date_within_14d_still_fails(env):
    d, ans = env
    ans["tv"] = date(2026, 11, 2)
    ss.get_next_earnings("CSCO", today=TODAY, force=True)
    st = ss.earnings_state("CSCO", TODAY)
    assert st["kind"] == "known" and st["date"] == "2026-11-02"
    r = _row("CSCO", st["kind"], st["date"])
    assert r["f_no_earnings_14d"] is False and r["earnings_none"] is False and r["earnings_estimated"] is False


def test_tv_drawings_live_gate(env, monkeypatch):
    d, ans = env
    monkeypatch.setattr(tvd, "Path", lambda p: d if str(p) == "/workspace/cache" else __import__("pathlib").Path(p))
    (d / "earn_SPY.json").write_text(json.dumps({"earnings_date": None, "source": "miss", "fetched_at": "2026-10-26T00:00:00Z"}))
    (d / "earn_X.json").write_text(json.dumps({"earnings_date": "2026-11-01", "source": "tradingview", "fetched_at": "2026-10-26T00:00:00Z"}))
    assert tvd.no_earnings_live("SPY", None, TODAY) is True
    assert tvd.no_earnings_live("X", None, TODAY) is False
    assert tvd.no_earnings_live("NEVER", None, TODAY) is False
