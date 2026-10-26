"""FinViz base screen (Eyal 2026-10-26): price > $10 and below SMA50 only; 'above SMA200' dropped."""
from urllib.parse import parse_qs, urlsplit

import stock_screen


def _filters(url):
    return set(parse_qs(urlsplit(url).query)["f"][0].split(","))


def test_screener_filters_without_sma200():
    assert _filters(stock_screen.SCREENER_URL) == {"sh_price_o10", "ta_sma50_pb"}
    assert "sma200" not in stock_screen.SCREENER_URL


def test_ownership_view_keeps_same_filters():
    url = stock_screen._screener_url(131)
    assert "v=131" in url and "v=111" not in url
    assert _filters(url) == {"sh_price_o10", "ta_sma50_pb"}


def test_with_filter_replace_and_add():
    base = "https://finviz.com/screener/etf?v=131&f=sh_price_o10,ta_sma50_pb&ft=4&o=ticker"
    assert "f=sh_price_20to50,ta_sma50_pb" in stock_screen._fv_with_filter(base, "sh_price_o10", "sh_price_20to50")
    assert "f=sh_avgvol_u50,sh_price_o10,ta_sma50_pb" in stock_screen._fv_with_filter(base, None, "sh_avgvol_u50")


def test_collect_partitions_large_query(monkeypatch):
    """A 5000-row query (beyond asc+desc paging) is read through its partitions."""
    universe = {f"T{i:04d}": (10 + (i % 200), i % 3) for i in range(5000)}  # (price, vol bucket)

    def match(url, t):
        price, vol = universe[t]
        f = parse_qs(urlsplit(url).query)["f"][0].split(",")
        bands = {"sh_price_o10": (10, 1e9), "sh_price_10to20": (10, 20), "sh_price_20to50": (20, 50),
                 "sh_price_50to100": (50, 100), "sh_price_o100": (100, 1e9)}
        for k in f:
            if k in bands and not (bands[k][0] <= price < bands[k][1]):
                return False
            if k == "sh_avgvol_u50" and vol != 0:
                return False
            if k == "sh_avgvol_o50" and vol == 0:
                return False
        return True

    def fake_query(url, own):
        rows = [t for t in universe if match(url, t)]
        assert len(rows) <= 2 * stock_screen.FV_PAGE_CAP, (url, len(rows))
        for t in rows:
            own[t] = {"inst_own": None, "short_float": None}
        return len(rows)

    def fake_page(url):
        return [], sum(1 for t in universe if match(url, t))

    monkeypatch.setattr(stock_screen, "_fv_query", fake_query)
    monkeypatch.setattr(stock_screen, "_fv_page", fake_page)
    own = {}
    total = stock_screen._fv_collect("https://finviz.com/screener/etf?v=131&f=sh_price_o10,ta_sma50_pb&ft=4&o=ticker", own)
    assert total == 5000 and len(own) == 5000
