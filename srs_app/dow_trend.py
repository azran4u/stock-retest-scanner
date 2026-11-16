"""Classic Dow structure on weekly swings (Eyal 2026-11-16: "uptrend = higher highs and higher lows, downtrend = lower
highs and lower lows, sideways = a range bounded above and below").

Swings: standard swing pivots with K weeks on each side (report_filters CONFIG tech_dow_k = 5); a swing high is a weekly
high strictly above the K highs before and after it (swing low: strictly below the K lows on both sides).
Comparison = the two most recent swing highs and the two most recent swing lows:
  HH + HL -> up,  LH + LL -> down,  otherwise mixed.
A newly broken swing counts at once (Dow: the trend changes when price takes out the last swing): when a weekly CLOSE
after the last confirmed swing high is above it (closing basis, the classic Dow rule; wicks do not break), the highest
high since is the latest high (a new HH not yet confirmed by K weeks); a weekly close below the last confirmed swing
low makes the lowest low since the latest low (a new LL).
Persistence (Dow: a trend is in effect until it gives a definite reversal signal), structure_persist / trend(): walk
the swings in time order; an uptrend stays up through a lower high until a LOWER LOW, a downtrend stays down through a
higher low until a HIGHER HIGH; mixed swings with no trend in effect = sideways (a range).
Spacing (Eyal 2026-11-16): consecutive swing highs, and consecutive swing lows, are at least tech_swing_min_gap_weeks
(8) weeks apart; two swings of the same type closer than that are merged into the more extreme one (higher high /
lower low).
Fewer than 2 swing highs or 2 swing lows -> 'sideways' (no structure to call).
Pure python (lists of floats), shared by report_filters.compute_technical and srs_app.expert_zone.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

UP, DOWN, SIDE = "up", "down", "sideways"
HE = {UP: "עלייה", DOWN: "ירידה", SIDE: "דשדוש"}


def pivots(a: Sequence[float], k: int, kind: str) -> List[int]:
    out = []
    for i in range(k, len(a) - k):
        nb = list(a[i - k:i]) + list(a[i + 1:i + k + 1])
        if (kind == "hi" and a[i] > max(nb)) or (kind == "lo" and a[i] < min(nb)):
            out.append(i)
    return out


def space(points: List[Tuple[int, float]], gap: int, kind: str) -> List[Tuple[int, float]]:
    """Eyal 2026-11-16: consecutive swings of the same type are at least `gap` weeks apart (~2-3 months). Two swings
    closer than that are one swing: keep the more extreme (the higher of two highs, the lower of two lows)."""
    out: List[Tuple[int, float]] = []
    for pt in sorted(points):
        if out and gap and pt[0] - out[-1][0] < gap:
            if (kind == "hi" and pt[1] > out[-1][1]) or (kind == "lo" and pt[1] < out[-1][1]):
                out[-1] = pt
            continue
        out.append(pt)
    return out


def structure(highs: Sequence[float], lows: Sequence[float], k: int = 3, window: Optional[int] = None,
              closes: Optional[Sequence[float]] = None, gap: int = 0) -> Dict[str, Any]:
    """{'trend', 'he', 'highs': [(i, v) x2], 'lows': [(i, v) x2], 'hh', 'hl', 'broken_hi', 'broken_lo', 'detail'}.
    window = only swings inside the last `window` bars (None = all)."""
    n = len(highs)
    i0 = 0 if not window else max(0, n - int(window))
    ph = space([(i, float(highs[i])) for i in pivots(highs, k, "hi") if i >= i0], gap, "hi")
    pl = space([(i, float(lows[i])) for i in pivots(lows, k, "lo") if i >= i0], gap, "lo")
    broken_hi = broken_lo = False
    if ph:
        j = ph[-1][0]
        tail = [(i, float(highs[i])) for i in range(j + 1, n)]
        if tail:
            bi = max(tail, key=lambda x: x[1])
            if (bi[1] > ph[-1][1]) if closes is None else any(float(closes[i]) > ph[-1][1] for i in range(j + 1, n)):
                ph = space(ph + [bi], gap, "hi")
                broken_hi = True
    if pl:
        j = pl[-1][0]
        tail = [(i, float(lows[i])) for i in range(j + 1, n)]
        if tail:
            bi = min(tail, key=lambda x: x[1])
            if (bi[1] < pl[-1][1]) if closes is None else any(float(closes[i]) < pl[-1][1] for i in range(j + 1, n)):
                pl = space(pl + [bi], gap, "lo")
                broken_lo = True
    out: Dict[str, Any] = {"trend": SIDE, "he": HE[SIDE], "highs": ph[-2:], "lows": pl[-2:], "hh": None, "hl": None,
                           "broken_hi": broken_hi, "broken_lo": broken_lo}
    if len(ph) < 2 or len(pl) < 2:
        out["detail"] = f"not enough swings ({len(ph)} highs, {len(pl)} lows with {k} weeks each side)"
        return out
    (_, h1), (_, h2) = ph[-2], ph[-1]
    (_, l1), (_, l2) = pl[-2], pl[-1]
    hh, lh, hl, ll = h2 > h1, h2 < h1, l2 > l1, l2 < l1
    out["hh"], out["hl"] = hh, hl
    if hh and hl:
        out["trend"] = UP
    elif lh and ll:
        out["trend"] = DOWN
    out["he"] = HE[out["trend"]]
    f = lambda v: f"{v:.2f}"
    out["detail"] = (f"{'HH' if hh else 'LH' if lh else 'EH'} {f(h1)} -> {f(h2)}{' (new, broken)' if broken_hi else ''}, "
                     f"{'HL' if hl else 'LL' if ll else 'EL'} {f(l1)} -> {f(l2)}{' (new, broken)' if broken_lo else ''}")
    return out


def structure_persist(highs, lows, k=3, window=None, closes=None, gap: int = 0) -> Dict[str, Any]:
    """Dow persistence: walk the swings in time order; HH+HL -> up, LH+LL -> down; an uptrend stays up through a lower
    high until a LOWER LOW (the last higher low is broken), a downtrend stays down through a higher low until a HIGHER
    HIGH; then sideways until the swings line up again."""
    n = len(highs)
    i0 = 0 if not window else max(0, n - int(window))
    base = structure(highs, lows, k, window, closes, gap)
    ph = space([(i, float(highs[i])) for i in pivots(highs, k, "hi") if i >= i0], gap, "hi")
    pl = space([(i, float(lows[i])) for i in pivots(lows, k, "lo") if i >= i0], gap, "lo")
    # provisional breaks (same as structure): the broken swing replaces / follows the last one
    if base["broken_hi"]:
        ph = space(ph + [tuple(base["highs"][-1])], gap, "hi")
    if base["broken_lo"]:
        pl = space(pl + [tuple(base["lows"][-1])], gap, "lo")
    ev = sorted([(i, "h", v) for i, v in ph] + [(i, "l", v) for i, v in pl])
    H: List[float] = []
    L: List[float] = []
    st = SIDE
    for _, kind, v in ev:
        (H if kind == "h" else L).append(v)
        if len(H) < 2 or len(L) < 2:
            continue
        hh, lh, hl, ll = H[-1] > H[-2], H[-1] < H[-2], L[-1] > L[-2], L[-1] < L[-2]
        if hh and hl:
            st = UP
        elif lh and ll:
            st = DOWN
        elif st == UP and kind == "l" and ll:
            st = SIDE
        elif st == DOWN and kind == "h" and hh:
            st = SIDE
    base["trend"], base["he"] = st, HE[st]
    return base


def trend(highs, lows, closes, k: int = 5, window=None, gap: int = 8) -> Dict[str, Any]:
    """The trend used by the scanner: Dow persistence with close-confirmed breaks, same-type swings >= gap weeks apart."""
    return structure_persist(highs, lows, k, window, closes, gap)
