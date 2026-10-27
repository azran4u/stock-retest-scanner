"""Duplicate price-series guard (Eyal 2026-10-27: 'AVDE and SCZ show the same chart'; they don't - two correlated
international ETFs - but a fetch that falls back to another symbol would, so the export flags identical series)."""
import math

from srs_app.series_guard import duplicate_series, flag_duplicates


def _walk(seed: int, n: int = 300, p0: float = 50.0):
    x, out = p0, []
    for i in range(n):
        x *= 1 + 0.01 * math.sin(seed * 1.7 + i * 0.37 + seed * i * 0.011)
        out.append((f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}", round(x, 2)))
    return out


def test_identical_series_flagged_both_ways():
    a = _walk(1)
    got = duplicate_series({"AVDE": a, "SCZ": list(a), "SPY": _walk(2)})
    assert got == {"AVDE": "SCZ", "SCZ": "AVDE"}


def test_correlated_but_different_not_flagged():
    a = _walk(3)
    b = [(d, round(c * 0.93 + 0.4, 2)) for d, c in a]          # same shape, different prices (AVDE vs SCZ, SPY vs VOO)
    assert duplicate_series({"A": a, "B": b}) == {}


def test_share_classes_allowed_and_short_series_ignored():
    a = _walk(4)
    assert duplicate_series({"GOOG": a, "GOOGL": list(a)}) == {}
    assert duplicate_series({"X": a[:30], "Y": a[:30]}) == {}


def test_mostly_identical_with_few_glitches_flagged():
    a = _walk(5)
    b = list(a)
    b[-3] = (b[-3][0], b[-3][1] + 0.5)                          # one bad print in the last 60 days
    assert duplicate_series({"P": a, "Q": b}) == {"P": "Q", "Q": "P"}


def test_flag_rows():
    a = _walk(6)
    rows = [{"ticker": "P"}, {"ticker": "Q"}, {"ticker": "R"}]
    n = flag_duplicates(rows, {"P": a, "Q": list(a), "R": _walk(7)})
    assert n == 2 and rows[0]["data_dup_of"] == "Q" and rows[1]["data_dup_of"] == "P" and rows[2]["data_dup_of"] is None
