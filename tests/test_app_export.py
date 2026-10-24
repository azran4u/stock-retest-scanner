"""App index: the 'hammer' badge / inclusion needs the must-haves ($vol, history, no earnings <=14d)."""
import json

import pandas as pd

from srs_app.export_data import build_index, hammer_ok

BASE = {"status": "FAIL", "needs_drawing": False, "f_bot_review": False, "f_tv_stale": False, "tv_found": None,
        "f_last_week_reversal": True, "f_dollar_vol": True, "f_history": True, "f_no_earnings_14d": True}


def _index(tmp_path, rows, watch_positions=()):
    df = pd.DataFrame([{**BASE, **r} for r in rows])
    csv = tmp_path / "latest.csv"
    df.to_csv(csv, index=False)
    (tmp_path / "positions.json").write_text(json.dumps({"positions": [{"ticker": t, "status": "open"} for t in watch_positions]}))
    return {r["ticker"]: r for r in build_index(tmp_path, report=csv)}


def test_hammer_needs_must_haves(tmp_path):
    idx = _index(tmp_path, [
        {"ticker": "GOOD"},
        {"ticker": "LOWVOL", "f_dollar_vol": False},                  # e.g. BBMC: $vol $4.1M
        {"ticker": "NOEARN", "f_no_earnings_14d": None},              # unknown earnings date = not passing
        {"ticker": "EARN", "f_no_earnings_14d": False},
        {"ticker": "SHORT", "f_history": False},
        {"ticker": "NOHAM", "f_last_week_reversal": False},
    ])
    assert idx["GOOD"]["badges"] == ["hammer"]
    for t in ("LOWVOL", "NOEARN", "EARN", "SHORT", "NOHAM"):
        assert t not in idx, t  # hammer alone no longer brings them into the app list


def test_other_inclusion_reasons_unchanged(tmp_path):
    idx = _index(tmp_path, [
        {"ticker": "PASSLV", "status": "PASS", "f_dollar_vol": False},
        {"ticker": "NDLV", "needs_drawing": True, "f_dollar_vol": False},
        {"ticker": "POSLV", "f_dollar_vol": False},
        {"ticker": "TVLV", "tv_found": "yes", "f_no_earnings_14d": False},
    ], watch_positions=["POSLV"])
    assert idx["PASSLV"]["badges"] == ["pass"]
    assert idx["NDLV"]["badges"] == ["needs_drawing"]
    assert idx["POSLV"]["badges"] == ["position"]
    assert idx["TVLV"]["badges"] == [] and idx["TVLV"]["tv_found"] is True


def test_hammer_ok_string_flags():
    assert hammer_ok({"f_last_week_reversal": "True", "f_dollar_vol": "True", "f_history": "True", "f_no_earnings_14d": "True"})
    assert not hammer_ok({"f_last_week_reversal": "True", "f_dollar_vol": "True", "f_history": "True", "f_no_earnings_14d": float("nan")})


def test_spark_series_weekly_ohlc():
    import base64
    from srs_app.export_data import spark_series, SPARK_Q
    idx = pd.bdate_range("2022-01-03", periods=900)
    c = pd.Series([10 + i * 0.01 for i in range(900)], index=idx)
    d = pd.DataFrame({"Open": c - 0.005, "High": c + 0.02, "Low": c - 0.02, "Close": c})
    sp = spark_series(d, weeks=156)
    q = base64.b64decode(sp["q"])
    assert sp["n"] == 156 and len(q) == 156 * 4
    o, h, l, cl = q[0::4], q[1::4], q[2::4], q[3::4]
    assert min(l) == 0 and max(h) == SPARK_Q
    assert all(h[i] >= max(o[i], cl[i]) and l[i] <= min(o[i], cl[i]) for i in range(156))
    assert list(cl) == sorted(cl)
    assert spark_series(d.iloc[:3]) is None


def test_attach_sectors_cache_and_missing(tmp_path):
    """List card sector/industry (Eyal 2026-10-24): fetched once, then served from the cache; unknown = None ('—')."""
    from datetime import datetime, timedelta, timezone
    from srs_app.export_data import attach_sectors
    cache = tmp_path / "sec.json"
    calls = []

    def fake(t):
        calls.append(t)
        return {"CSCO": {"sector": "Technology", "industry": "Communication Equipment", "src": "finviz"}}.get(t, {})

    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    rows = [{"ticker": "CSCO"}, {"ticker": "ZZZZ"}]
    assert attach_sectors(rows, cache, fake, now) == 2
    assert rows[0]["sector"] == "Technology" and rows[0]["industry"] == "Communication Equipment"
    assert rows[1]["sector"] is None and rows[1]["industry"] is None
    # next day: the hit is cached, the miss is not retried yet (7-day miss TTL)
    rows = [{"ticker": "CSCO"}, {"ticker": "ZZZZ"}]
    assert attach_sectors(rows, cache, fake, now + timedelta(days=1)) == 0 and rows[0]["sector"] == "Technology"
    # after the miss TTL the unknown one is retried; a failed re-fetch never wipes a known sector
    assert attach_sectors([{"ticker": "ZZZZ"}], cache, fake, now + timedelta(days=8)) == 1
    later = [{"ticker": "CSCO"}]
    calls.clear()
    assert attach_sectors(later, cache, lambda t: {}, now + timedelta(days=200)) == 1
    assert later[0]["sector"] == "Technology"
    # no fetcher (SRS_NO_NET): cache only
    rows = [{"ticker": "CSCO"}, {"ticker": "NEW"}]
    import os
    os.environ["SRS_NO_NET"] = "1"
    try:
        assert attach_sectors(rows, cache, None, now) == 0
    finally:
        del os.environ["SRS_NO_NET"]
    assert rows[0]["sector"] == "Technology" and rows[1]["sector"] is None


def test_finviz_sector_parser_current_and_legacy_layout():
    from bs4 import BeautifulSoup
    from srs.info import parse_sector_industry
    cur = ('<div class="quote-header_categories"><a href="screener?v=111&f=sec_technology" class="quote-header_category">Technology</a>'
           '<a href="screener?v=111&f=ind_communicationequipment" class="quote-header_category">Communication Equipment</a>'
           '<a href="screener?v=111&f=geo_usa">USA</a></div>')
    assert parse_sector_industry(BeautifulSoup(cur, "lxml")) == ("Technology", "Communication Equipment")
    old = '<div class="quote-links"><a class="tab-link">Industrials</a><a class="tab-link">Tools &amp; Accessories</a></div>'
    assert parse_sector_industry(BeautifulSoup(old, "lxml")) == ("Industrials", "Tools & Accessories")


def test_spark_ma_and_attach_fib():
    import base64
    from datetime import date, timedelta
    from srs_app.export_data import attach_fib, spark_ma
    bars = []
    for i in range(700):
        d = date(2023, 1, 2) + timedelta(days=i)
        if d.weekday() < 5:
            c = 100 + i * 0.05
            bars.append([d.isoformat(), c, c + 1, c - 1, c, 1000])
    ma = spark_ma(bars, 50)
    q = base64.b64decode(ma["q"])
    assert len(q) == 50 * 4 and q[-1] != 255 and max(q) <= 255
    rows = [{"ticker": "A", "current_price": 125.0, "tv_zone_top": 126, "tv_zone_bottom": 124}, {"ticker": "B"}]
    attach_fib(rows, {"A": {"low": 100, "low_date": "2026-01-05", "high": 150, "high_date": "2026-06-01", "atr_w": 4.0}})
    assert rows[0]["fib_price_level"] == 0.5 and rows[0]["fib_zone_levels"] == [0.5] and rows[0]["fib_confluence"] == "price@0.5, zone@0.5"
    assert rows[1]["fib_low"] is None and rows[1]["fib_confluence"] is None
