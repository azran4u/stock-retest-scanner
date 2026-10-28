"""app/data/earnings.json field (chart 'E' markers, Eyal 2026-10-28): past report dates with BMO/AMC + EPS from the
Yahoo calendar, next date from the scanner row, funds skipped, cache fallback, bounded calls, refresh after a report."""
import json
from datetime import date

import pandas as pd

from srs_app import earnings_marks as em


def _frame():
    idx = pd.DatetimeIndex(pd.to_datetime([
        "2026-12-16 07:00", "2026-09-30 07:00", "2026-06-17 16:05", "2026-03-18 00:00", "2019-01-10 07:00",
    ])).tz_localize("America/New_York")
    return pd.DataFrame({"EPS Estimate": [4.05, 4.08, 3.12, 2.51, 1.0],
                         "Reported EPS": [float("nan"), 4.40, 3.16, float("nan"), 1.1],
                         "Surprise(%)": [float("nan"), 7.96, 1.35, float("nan"), 10.0]}, index=idx)


def test_rows_from_frame_timing_and_eps():
    rows = em.rows_from_frame(_frame())
    by = {r["d"]: r for r in rows}
    assert [r["d"] for r in rows] == sorted(by)
    assert by["2026-09-30"] == {"d": "2026-09-30", "t": "bmo", "e": 4.08, "a": 4.4, "s": 7.96}
    assert by["2026-06-17"]["t"] == "amc"
    assert by["2026-03-18"]["t"] is None and by["2026-03-18"]["a"] is None  # midnight = unknown, NaN = null (never invented)


def test_build_past_next_funds_and_since(tmp_path):
    calls = []

    def fetch(t):
        calls.append(t)
        return _frame()

    rows = [{"ticker": "JBL", "earnings_date": "2026-12-10", "earnings_estimated": True}, {"ticker": "SPY"}]
    out = em.build(rows, ["JBL", "SPY"], tmp_path, is_fund=lambda t: t == "SPY", today=date(2026, 10, 28),
                   since="2021-10-28", fetch=fetch, workers=1)
    assert calls == ["JBL"]                      # the fund is never asked
    assert "SPY" not in out
    j = out["JBL"]
    assert [p["d"] for p in j["p"]] == ["2026-03-18", "2026-06-17", "2026-09-30"]  # past only, within the window
    assert j["n"] == "2026-12-10" and j["ne"] is True and j["src"] == "yahoo"     # scanner's next date wins
    json.dumps(out)  # serialisable
    # cached: a second build does not call Yahoo again
    em.build(rows, ["JBL"], tmp_path, is_fund=lambda t: False, today=date(2026, 10, 28), fetch=fetch, workers=1)
    assert calls == ["JBL"]


def test_next_from_yahoo_when_scanner_has_none(tmp_path):
    out = em.build([{"ticker": "JBL"}], ["JBL"], tmp_path, is_fund=lambda t: False, today=date(2026, 10, 28),
                   fetch=lambda t: _frame(), workers=1)
    assert out["JBL"]["n"] == "2026-12-16" and out["JBL"]["ne"] is True and out["JBL"]["nt"] == "bmo"


def test_fallback_to_scanner_caches_on_timeout(tmp_path):
    (tmp_path / "earnhist_KNX.json").write_text(json.dumps({"dates": ["2026-01-21", "2026-04-22", "2026-11-20"]}))
    (tmp_path / "earn_KNX.json").write_text(json.dumps({"last_earnings_date": "2026-10-21"}))

    def bounded(fn, timeout, *a):
        raise TimeoutError("get_earnings_dates timed out after 25s")

    out = em.build([{"ticker": "KNX"}], ["KNX"], tmp_path, is_fund=lambda t: False, today=date(2026, 10, 28),
                   fetch=lambda t: _frame(), bounded=bounded, workers=1)
    k = out["KNX"]
    assert k["src"] == "cache" and [p["d"] for p in k["p"]] == ["2026-01-21", "2026-04-22", "2026-10-21"]
    assert all(p["a"] is None and p["e"] is None for p in k["p"])


def test_breaker_stops_asking(tmp_path):
    n = []

    def bounded(fn, timeout, *a):
        n.append(1)
        raise TimeoutError("timed out")

    em.build([], [f"T{i}" for i in range(8)], tmp_path, is_fund=lambda t: False, today=date(2026, 10, 28),
             fetch=lambda t: None, bounded=bounded, workers=1)
    assert len(n) == em.BREAKER


def test_refresh_after_upcoming_report_passes(tmp_path):
    c = {"fetched_at": "2026-10-20T20:00:00+00:00", "rows": [{"d": "2026-10-22", "t": "amc", "e": 1.0, "a": None, "s": None}]}
    assert em._needs_refresh(c, date(2026, 10, 28), None) is True
    c2 = {**c, "fetched_at": "2026-10-27T20:00:00+00:00"}
    assert em._needs_refresh(c2, date(2026, 10, 28), None) is False
