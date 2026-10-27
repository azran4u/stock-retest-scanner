"""Duplicate price-series guard for the app export (Eyal 2026-10-27: "ADVE and SCZ show the same chart").

Investigation: AVDE (Avantis International Equity) and SCZ (iShares MSCI EAFE Small-Cap) have different, correct data
(closes match TradingView / yfinance, daily-return correlation 0.965, price ratio 0.98-1.09) - two developed-ex-US ETFs
that simply move together. No identical series in hist_cache (6,658) or the app candles (466). This guard makes sure a
real duplicate (a fetch that silently returned another symbol's history) can never slip into the app unnoticed:
two tickers whose last WINDOW closes are equal to the cent on >= SHARE of the common days are flagged
(row['data_dup_of'] = the other ticker; the app shows a warning). Legit pairs (share classes) are allowed.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

WINDOW = 60          # last trading days compared
SHARE = 0.95         # share of equal closes (to the cent) that counts as the same series
MIN_DAYS = 40        # shorter histories are not judged
ALLOW = {frozenset(p) for p in [("GOOG", "GOOGL"), ("BRK.A", "BRK.B"), ("BRK-A", "BRK-B"), ("FOX", "FOXA"),
                                ("NWS", "NWSA"), ("LBRDA", "LBRDK"), ("BF.A", "BF.B"), ("BF-A", "BF-B")]}

Series = Sequence[Tuple[str, float]]   # [(date 'YYYY-MM-DD', close)]


def _tail(s: Series) -> Dict[str, int]:
    return {d: int(round(float(c) * 100)) for d, c in list(s)[-WINDOW:] if c is not None}


def duplicate_series(series: Dict[str, Series]) -> Dict[str, str]:
    """{ticker: other ticker with the same series}. Bucketed by a coarse fingerprint (median close in cents of the
    window, rounded to 1%) so the check is ~linear; candidates in a bucket are compared day by day."""
    tails = {t: _tail(s) for t, s in series.items()}
    tails = {t: m for t, m in tails.items() if len(m) >= MIN_DAYS}
    buckets: Dict[int, List[str]] = defaultdict(list)
    for t, m in tails.items():
        v = sorted(m.values())
        med = v[len(v) // 2]
        key = int(round(math.log(max(med, 1)) * 100))   # ~1% buckets
        for k in (key - 1, key, key + 1):
            buckets[k].append(t)
    out: Dict[str, str] = {}
    seen = set()
    for ts in buckets.values():
        for i, a in enumerate(ts):
            for b in ts[i + 1:]:
                pair = frozenset((a, b))
                if a == b or pair in seen or pair in ALLOW:
                    continue
                seen.add(pair)
                ma, mb = tails[a], tails[b]
                common = set(ma) & set(mb)
                if len(common) < MIN_DAYS:
                    continue
                eq = sum(1 for d in common if ma[d] == mb[d])
                if eq / len(common) >= SHARE:
                    out.setdefault(a, b)
                    out.setdefault(b, a)
    return out


def flag_duplicates(rows: Iterable[dict], series: Dict[str, Series]) -> int:
    """row['data_dup_of'] = other ticker (None = fine). Returns the number of flagged rows."""
    dup = duplicate_series(series)
    n = 0
    for r in rows:
        r["data_dup_of"] = dup.get(r["ticker"])
        if r["data_dup_of"]:
            n += 1
            print(f"  [app data] WARNING: {r['ticker']} price series identical to {r['data_dup_of']} - check the fetch")
    return n
