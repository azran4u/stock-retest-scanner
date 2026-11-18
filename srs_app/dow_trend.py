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


def trend(highs, lows, closes, k: int = 5, window=None, gap: int = 8, swing: str = "zigzag",
          rev: Optional[float] = None, tol: Optional[float] = None) -> Dict[str, Any]:
    """The trend used by the scanner. swing='zigzag' (v5, default since 2026-11-16 evening): Dow on ZigZag swings
    (trend_v5); swing='pivot' = v4 (K-week pivots, structure_persist)."""
    if swing == "pivot":
        return structure_persist(highs, lows, k, window, closes, gap)
    return trend_v5(highs, lows, closes, REV_ATR if rev is None else rev, TOL_ATR if tol is None else tol, gap, window)


# ------------------------------------------------------------------------------------------- v5 (2026-11-16, evening)
# v4 used symmetric K=5 pivots. In a fast advance (CRWD Mar-Oct 2026: 86 -> 287) no weekly low is below the 5 lows
# BEFORE it, so the pullback lows (Jun 154, Jul 174, Aug 181) were never swings and the Feb 85.68 low stayed the "last
# swing low" -> LL -> sideways. v5 = the standard ZigZag swing definition (alternating swings, a swing is confirmed
# when price reverses >= REV_ATR weekly ATR from the extreme), the same-type spacing (>= gap weeks) is kept by merging
# while preserving alternation, and a small tolerance (TOL_ATR x weekly ATR) separates a real break / higher / lower
# swing from an 'equal' one (EQIX 2026-10: closes 986 / 955 under the 989 July floor, highs 1118.65 vs 1103.95 = a
# range, not a downtrend).
REV_ATR = 2.0
TOL_ATR = 0.25


def wilder_atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> List[float]:
    out: List[float] = []
    a = None
    for i in range(len(highs)):
        tr = highs[i] - lows[i] if i == 0 else max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                                                     abs(lows[i] - closes[i - 1]))
        if i < n:
            a = tr if a is None else (a * i + tr) / (i + 1)
        else:
            a = (a * (n - 1) + tr) / n
        out.append(float(a))
    return out


def zigzag(highs: Sequence[float], lows: Sequence[float], atr: Sequence[float], rev: float = REV_ATR
           ) -> Tuple[List[Tuple[int, str, float]], Optional[Tuple[int, str, float]]]:
    """Alternating swings [(i, 'h'|'l', v)], each confirmed by a reversal >= rev x ATR(at the reversal bar) from it;
    plus the running (unconfirmed) extreme of the last leg."""
    n = len(highs)
    if n == 0:
        return [], None
    piv: List[Tuple[int, str, float]] = []
    d = None  # None = no direction yet; 'up' = tracking a high; 'down' = tracking a low
    hi, lo = (0, float(highs[0])), (0, float(lows[0]))
    for t in range(1, n):
        th = rev * float(atr[t])
        H, L = float(highs[t]), float(lows[t])
        if d is None:
            if H > hi[1]:
                hi = (t, H)
            if L < lo[1]:
                lo = (t, L)
            if hi[1] - L >= th and hi[0] < t and hi[0] >= lo[0]:
                piv.append((hi[0], "h", hi[1])); d = "down"; lo = (t, L)
            elif H - lo[1] >= th and lo[0] < t and lo[0] >= hi[0]:
                piv.append((lo[0], "l", lo[1])); d = "up"; hi = (t, H)
            continue
        if d == "up":
            if H > hi[1]:
                hi = (t, H)
            elif hi[1] - L >= th:
                piv.append((hi[0], "h", hi[1])); d = "down"; lo = (t, L)
        else:
            if L < lo[1]:
                lo = (t, L)
            elif H - lo[1] >= th:
                piv.append((lo[0], "l", lo[1])); d = "up"; hi = (t, H)
    ext = None if d is None else ((hi[0], "h", hi[1]) if d == "up" else (lo[0], "l", lo[1]))
    return piv, ext


def space_alt(piv: List[Tuple[int, str, float]], gap: int) -> List[Tuple[int, str, float]]:
    """Eyal's spacing on an alternating list: two swings of the same type < gap weeks apart are one swing (the more
    extreme kept); the swing of the other type between them goes with the dropped one, and of the two remaining
    same-type neighbours the more extreme is kept, so the list stays alternating."""
    p = list(piv)
    if not gap:
        return p
    changed = True
    while changed:
        changed = False
        for j in range(len(p) - 2):
            a, c = p[j], p[j + 2]
            if c[0] - a[0] >= gap:
                continue
            better_c = c[2] > a[2] if a[1] == "h" else c[2] < a[2]
            if better_c:      # drop a and the less extreme of (p[j-1], p[j+1])
                if j - 1 >= 0:
                    x, y = p[j - 1], p[j + 1]
                    worse = j - 1 if ((x[2] < y[2]) if x[1] == "h" else (x[2] > y[2])) else j + 1
                    for q in sorted({j, worse}, reverse=True):
                        del p[q]
                else:
                    del p[j]   # first swing in the list: no left neighbour, drop it (alternation kept)
            else:             # drop c and the less extreme of (p[j+1], p[j+3])
                if j + 3 < len(p):
                    x, y = p[j + 1], p[j + 3]
                    worse = j + 1 if ((x[2] < y[2]) if x[1] == "h" else (x[2] > y[2])) else j + 3
                    for q in sorted({j + 2, worse}, reverse=True):
                        del p[q]
                else:
                    del p[j + 2]
                    if j + 2 < len(p):   # keep alternation: drop the less extreme of the two now-adjacent swings
                        x, y = p[j + 1], p[j + 2]
                        del p[j + 1 if ((x[2] < y[2]) if x[1] == "h" else (x[2] > y[2])) else j + 2]
            changed = True
            break
    return p


def trend_v5(highs, lows, closes, rev: float = REV_ATR, tol: float = TOL_ATR, gap: int = 8,
             window: Optional[int] = None) -> Dict[str, Any]:
    """Dow on ZigZag swings. Order of the walk (time): each new swing is compared with the previous swing of the same
    type: higher / lower only when the difference exceeds tol x ATR (else 'equal'). HH+HL -> up, LH+LL -> down; an
    uptrend stays up until a LOWER LOW, a downtrend stays down until a HIGHER HIGH (Dow: in force until a definite
    reversal); mixed with no trend in force = sideways. The latest swing low (high) is also broken by a weekly CLOSE
    more than tol x ATR beyond it (closing basis) -> the lowest low (highest high) since = the new swing."""
    h = [float(x) for x in highs]; l = [float(x) for x in lows]; c = [float(x) for x in closes]
    n = len(h)
    atr = wilder_atr(h, l, c)
    piv, ext = zigzag(h, l, atr, rev)
    piv = space_alt(piv, gap)
    i0 = 0 if not window else max(0, n - int(window))
    piv = [p for p in piv if p[0] >= i0]
    ph = [(i, v) for i, k_, v in piv if k_ == "h"]
    pl = [(i, v) for i, k_, v in piv if k_ == "l"]
    a_now = atr[-1] if atr else 0.0
    broken_hi = broken_lo = False
    ev = list(piv)
    if ph:
        j, v = ph[-1]
        if any(c[i] > v + tol * a_now for i in range(j + 1, n)):
            bi = max(range(j + 1, n), key=lambda i: h[i])
            ev.append((bi, "h", h[bi])); broken_hi = True
    if pl:
        j, v = pl[-1]
        if any(c[i] < v - tol * a_now for i in range(j + 1, n)):
            bi = min(range(j + 1, n), key=lambda i: l[i])
            ev.append((bi, "l", l[bi])); broken_lo = True
    ev.sort()
    H: List[Tuple[int, float]] = []
    L: List[Tuple[int, float]] = []
    st = SIDE
    cmp = {"h": None, "l": None}
    for i, kind, v in ev:
        S = H if kind == "h" else L
        if S and gap and i - S[-1][0] < gap:
            # a provisional break closer than gap weeks to the last same-type swing = the same swing (more extreme)
            if not ((kind == "h" and v > S[-1][1]) or (kind == "l" and v < S[-1][1])):
                continue
            S[-1] = (i, v)
        else:
            S.append((i, v))
        if len(S) >= 2:
            tl = tol * atr[i]
            d_ = S[-1][1] - S[-2][1]
            cmp[kind] = "higher" if d_ > tl else "lower" if d_ < -tl else "equal"
        if cmp["h"] is None or cmp["l"] is None:
            continue
        hh, lh = cmp["h"] == "higher", cmp["h"] == "lower"
        hl, ll = cmp["l"] == "higher", cmp["l"] == "lower"
        if hh and hl:
            st = UP
        elif lh and ll:
            st = DOWN
        elif st == UP and kind == "l" and ll:
            st = SIDE
        elif st == DOWN and kind == "h" and hh:
            st = SIDE
    out: Dict[str, Any] = {"trend": st, "he": HE[st], "highs": H[-2:], "lows": L[-2:],
                           "hh": cmp["h"] == "higher" if cmp["h"] else None,
                           "hl": cmp["l"] == "higher" if cmp["l"] else None,
                           "broken_hi": broken_hi, "broken_lo": broken_lo, "swings": ev}
    if len(H) < 2 or len(L) < 2:
        out["detail"] = f"not enough swings ({len(H)} highs, {len(L)} lows; ZigZag {rev:g} ATR, {gap}w apart)"
        return out
    f = lambda x: f"{x:.2f}"
    tag = {"higher": ("HH", "HL"), "lower": ("LH", "LL"), "equal": ("EH", "EL")}
    out["detail"] = (f"{tag[cmp['h']][0]} {f(H[-2][1])} -> {f(H[-1][1])}{' (new, broken)' if broken_hi else ''}, "
                     f"{tag[cmp['l']][1]} {f(L[-2][1])} -> {f(L[-1][1])}{' (new, broken)' if broken_lo else ''}")
    return out
