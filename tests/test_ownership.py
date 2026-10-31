"""srs_app.ownership.attach_ownership: inst own % / short float % per app row (Eyal 2026-10-31)."""
import json
from datetime import datetime, timedelta, timezone

from srs_app.ownership import _pct_num, attach_ownership

NOW = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
BULK = {"fetched_at": "2026-10-30T21:04:02Z",
        "tickers": {"CSCO": {"inst_own": 0.8352, "short_float": 0.0153}, "URA": {"inst_own": None, "short_float": None},
                    "PL": {"inst_own": 0.5, "short_float": 0.2}}}


def test_pct_num():
    assert _pct_num("92.37%") == 92.37 and _pct_num("-") is None and _pct_num("") is None
    assert _pct_num(0.8352) == 83.52 and _pct_num(None) is None and _pct_num(float("nan")) is None


def test_report_row_wins_then_bulk_then_etf_dash(tmp_path):
    rows = [{"ticker": "PL", "inst_own_pct": 60.75, "short_float_pct": 12.87},
            {"ticker": "CSCO", "inst_own_pct": None, "short_float_pct": None},
            {"ticker": "URA", "inst_own_pct": None, "short_float_pct": None}]
    calls = []
    st = attach_ownership(rows, bulk=BULK, cache_path=tmp_path / "c.json", fetch=lambda t: calls.append(t), now=NOW)
    assert rows[0]["inst_own_pct"] == 60.75 and rows[0]["short_float_pct"] == 12.87  # report value kept
    assert rows[1]["inst_own_pct"] == 83.52 and rows[1]["short_float_pct"] == 1.53 and rows[1]["own_date"] == "2026-10-30"
    assert rows[2]["inst_own_pct"] is None and rows[2]["short_float_pct"] is None and rows[2]["own_date"] is None  # ETF
    assert calls == [] and st["inst"] == 2 and st["short"] == 2  # universe tickers never hit the quote page


def test_off_universe_rows_fetch_once_then_cache(tmp_path):
    cp = tmp_path / "c.json"
    rows = [{"ticker": "ADP", "status": "OUT"}, {"ticker": "AMZA", "status": "OUT"}]
    got = {"ADP": {"inst_own_pct": 92.37, "short_float_pct": 2.58}, "AMZA": {"inst_own_pct": None, "short_float_pct": None}}
    calls = []
    st = attach_ownership(rows, bulk=BULK, cache_path=cp, fetch=lambda t: (calls.append(t), got[t])[1], now=NOW)
    assert calls == ["ADP", "AMZA"] and st["fetched"] == 2
    assert rows[0]["inst_own_pct"] == 92.37 and rows[0]["short_float_pct"] == 2.58 and rows[0]["own_date"] == "2026-10-31"
    assert rows[1]["inst_own_pct"] is None
    # next run (3 days later): both cached (hit TTL 7d, miss TTL 14d) -> no network
    rows2 = [{"ticker": "ADP"}, {"ticker": "AMZA"}]
    calls.clear()
    attach_ownership(rows2, bulk=BULK, cache_path=cp, fetch=lambda t: (calls.append(t), got[t])[1], now=NOW + timedelta(days=3))
    assert calls == [] and rows2[0]["inst_own_pct"] == 92.37
    # 8 days later the hit is stale -> refetched; the miss is not yet
    attach_ownership([{"ticker": "ADP"}, {"ticker": "AMZA"}], bulk=BULK, cache_path=cp,
                     fetch=lambda t: (calls.append(t), got[t])[1], now=NOW + timedelta(days=8))
    assert calls == ["ADP"]


def test_breaker_and_cap_never_stall(tmp_path):
    cp = tmp_path / "c.json"
    cp.write_text(json.dumps({"OLD": {"inst_own_pct": 50.0, "short_float_pct": 1.0, "fetched": "2026-01-01T00:00:00+00:00"}}))
    calls = []

    def boom(t):
        calls.append(t)
        raise RuntimeError("403 Forbidden")
    rows = [{"ticker": f"X{i}"} for i in range(20)] + [{"ticker": "OLD"}]
    st = attach_ownership(rows, bulk=BULK, cache_path=cp, fetch=boom, now=NOW, breaker=3)
    assert len(calls) == 3 and st["tripped"] == 1 and st["failed"] == 3
    assert rows[-1]["inst_own_pct"] == 50.0  # stale cached value still shown rather than nothing
    calls.clear()
    st = attach_ownership([{"ticker": f"Y{i}"} for i in range(20)], bulk=BULK, cache_path=cp,
                          fetch=lambda t: (calls.append(t), {"inst_own_pct": 1.0})[1], now=NOW, max_fetch=5)
    assert len(calls) == 5 and st["fetched"] == 5


def test_budget(tmp_path):
    calls = []
    st = attach_ownership([{"ticker": f"Z{i}"} for i in range(5)], bulk=BULK, cache_path=tmp_path / "c.json",
                          fetch=lambda t: calls.append(t) or {}, now=NOW, budget_s=-1)
    assert calls == [] and st["tripped"] == 1


def test_no_net_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SRS_NO_NET", "1")
    rows = [{"ticker": "ADP"}]
    st = attach_ownership(rows, bulk=BULK, cache_path=tmp_path / "c.json", now=NOW)
    assert st["fetched"] == 0 and rows[0]["inst_own_pct"] is None
