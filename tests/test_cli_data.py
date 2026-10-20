import pandas as pd

from srs.data import load_cached, parse_tickers_file, save_cached, yf_symbol
from srs.cli import main


def test_yf_symbol():
    assert yf_symbol("NYSE:MOG.A") == "MOG-A"
    assert yf_symbol(" nasdaq:aapl ") == "AAPL"
    assert yf_symbol("BRK.B") == "BRK-B"


def test_parse_tickers_file(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("# my list\nAAPL\nNASDAQ:MSFT\n\nNYSE:MOG.A, NYSE:PH  # comment\n###SECTION\naapl\n")
    assert parse_tickers_file(f) == ["AAPL", "MSFT", "MOG-A", "PH"]


def test_cache_roundtrip_and_cli(tmp_path, capsys):
    idx = pd.bdate_range("2022-01-03", periods=400)
    d = pd.DataFrame({"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 1000}, index=idx)
    save_cached("XYZ", d, tmp_path)
    back = load_cached("xyz", tmp_path)
    assert len(back) == 400 and back.index[0] == idx[0]
    assert main(["weekly", "XYZ", "--cache-dir", str(tmp_path), "--last", "3", "--json"]) == 0
    assert '"week"' in capsys.readouterr().out
    lst = tmp_path / "l.txt"
    lst.write_text("XYZ\nNOPE\n")
    assert main(["trend", str(lst), "--cache-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "XYZ" in out and "not in cache" in out


def test_finviz_earnings_parsing():
    from datetime import date
    from srs.info import _cap, _earn, _pct
    t = date(2026, 10, 20)
    assert _earn("Nov 04 BMO", t) == "2026-11-04"
    assert _earn("Aug 06 BMO", t) is None          # last report, not the next one
    assert _earn("Jan 22 AMC", date(2026, 12, 1)) == "2027-01-22"
    assert _pct("91.11%") == 0.9111 and _pct("-") is None
    assert _cap("119.36B") == 119.36e9
