"""TradingView symbol mapping for the app copy button (srs_app/tv_symbols.py)."""
from datetime import datetime, timezone

from srs_app.tv_symbols import attach_tv_symbols, from_url, pick, tv_name


def test_tv_name_class_shares():
    assert tv_name("BRK-B") == "BRK.B"
    assert tv_name("crd-a") == "CRD.A"
    assert tv_name("BF/B") == "BF.B"
    assert tv_name("MOG.A") == "MOG.A"


def test_pick_primary_us_listing_no_otc():
    rows = [{"s": "OTC:SNXX", "exchange": "OTC", "is_primary": True},
            {"s": "NYSE:SNX", "exchange": "NYSE", "is_primary": True}]
    assert pick(rows) == "NYSE:SNX"
    assert pick([{"s": "OTC:ABC", "exchange": "OTC", "is_primary": True}]) is None
    assert pick([{"s": "CBOE:ARKK", "exchange": "CBOE", "is_primary": False},
                 {"s": "NASDAQ:ARKK", "exchange": "NASDAQ", "is_primary": False}]) == "NASDAQ:ARKK"
    assert pick([{"s": "NASDAQ:X", "exchange": "NASDAQ", "is_primary": False},
                 {"s": "NYSE:X", "exchange": "NYSE", "is_primary": True}]) == "NYSE:X"


def test_from_url():
    assert from_url("https://www.tradingview.com/chart/?symbol=NYSE:PNC", "PNC") == "NYSE:PNC"
    assert from_url("https://www.tradingview.com/chart/?symbol=NYSEARCA%3ASPY", "SPY") == "AMEX:SPY"
    assert from_url("https://www.tradingview.com/chart/?symbol=NYSE:BRK-B", "BRK-B") == "NYSE:BRK.B"
    assert from_url("https://www.tradingview.com/chart/?symbol=OTC:XYZ", "XYZ") is None
    assert from_url(None, "XYZ") is None


def test_attach_scanner_wins_then_url_fallback_and_cache(tmp_path):
    cache = tmp_path / "c.json"
    calls = []

    def fake(names):
        calls.append(list(names))
        return {"SNX": [{"s": "NYSE:SNX", "exchange": "NYSE", "is_primary": True}],
                "BRK.B": [{"s": "NYSE:BRK.B", "exchange": "NYSE", "is_primary": False}],
                "SPY": [{"s": "AMEX:SPY", "exchange": "AMEX", "is_primary": True}]}

    rows = [{"ticker": "SNX", "tradingview_url": "https://www.tradingview.com/chart/?symbol=NASDAQ:SNX"},
            {"ticker": "BRK-B"}, {"ticker": "SPY"},
            {"ticker": "ZZZ", "tradingview_url": "https://www.tradingview.com/chart/?symbol=NASDAQ:ZZZ"},
            {"ticker": "QQQQ"}]
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    assert attach_tv_symbols(rows, cache, fake, now) == 5
    assert [r["tv_symbol"] for r in rows] == ["NYSE:SNX", "NYSE:BRK.B", "AMEX:SPY", "NASDAQ:ZZZ", None]
    # cached: no second lookup for hits within TTL (misses ZZZ / QQQQ are retried)
    assert attach_tv_symbols([{"ticker": "SNX"}], cache, fake, now) == 0
    assert len(calls) == 1


def test_scanner_down_keeps_fallback(tmp_path):
    rows = [{"ticker": "PNC", "tradingview_url": "https://www.tradingview.com/chart/?symbol=NYSE:PNC"}]
    assert attach_tv_symbols(rows, tmp_path / "c.json", lambda n: {}, datetime(2026, 10, 27, tzinfo=timezone.utc)) == 0
    assert rows[0]["tv_symbol"] == "NYSE:PNC"
