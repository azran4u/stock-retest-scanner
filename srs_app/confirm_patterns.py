"""Confirmation patterns on the retest level ('תבניות אישור', Eyal 2026-11-16): standard bullish reversal candlestick
patterns that form ON the support level after a pullback into it. They are EVIDENCE only (a confirmation of the level's
strength and an entry signal), never a PASS gate: they do not change PASS, the falling-knife or the earnings-week rules.

Patterns (textbook definitions; the multi-bar TA-Lib ones are a line-by-line port of TA-Lib 0.6 with its default candle
settings, cross-checked against TA-Lib in tests/test_confirm_patterns.py):
  engulf   בליעה שורית          TA-Lib CDLENGULFING (bullish): candle 1 black, candle 2 white and its real body engulfs
                                 candle 1's body (close2 >= open1 and open2 < close1, or close2 > open1 and open2 <= close1);
                                 + Nison: the white body is not short (> BodyShort average)
  mstar    כוכב בוקר            TA-Lib CDLMORNINGSTAR (penetration 0.3): 1 long black body, 2 short body whose body gaps
                                 down from 1's body, 3 white body longer than 'short' closing above close1 + 30% of body1
  mdoji    כוכב בוקר דוג'י       TA-Lib CDLMORNINGDOJISTAR (penetration 0.3): as mstar, the middle candle is a doji
  pierce   קו חודר              TA-Lib CDLPIERCING: 1 long black, 2 long white opening under low1 and closing above the
                                 midpoint of body1 but under open1
  inside3  שלושה מבפנים למעלה    TA-Lib CDL3INSIDE (bullish = harami confirmed): 1 long black, 2 short body inside body1,
                                 3 white closing above open1
  hammerc  פטיש + נר אישור       the scanner's textbook hammer (expert_zone.hammer_shape 'H': lower shadow >= 2x body,
                                 >= 2/3 of the range = body in the top third, upper shadow <= 15% of the range), followed by
                                 a white candle closing above the hammer's HIGH (StockCharts / Bulkowski confirmation)
  tweezer  תחתית פינצטה          Nison / Investopedia tweezer bottom: candle 1 black, candle 2 white, matching lows
                                 (|low2 - low1| <= TA-Lib 'Equal' = 5% of the average range of the 5 bars before); the white
                                 candle shows real buying: body > BodyShort average and close above the black body's midpoint
TA-Lib default candle settings used (CandleAverage = factor x average of the setting's range over `period` bars BEFORE the
bar; RealBody = |c - o|, HighLow = h - l, Shadows = (upper + lower) / 2):
  BodyLong RealBody 10 x1.0 · BodyShort RealBody 10 x1.0 · BodyDoji HighLow 10 x0.1 · Equal HighLow 5 x0.05

Context gates (TA-Lib leaves the trend to the user; Nison / Bulkowski: a reversal pattern needs a prior decline to
reverse). Constants in CONFIRM:
  pullback : the pattern's low is the lowest low of the `prior_bars` (5) bars before it and is at least `decline_atr`
             (1.0) ATR(14) under their highest high (price came DOWN into the pattern)
  on level : the pattern's low actually touches the zone: bottom - tol <= low <= top + tol,
             tol = min(`zone_tol_atr` 0.1 ATR(14) of the same timeframe, `zone_tol_pct` 1% of the zone top) (v2; v1 used
             0.5 ATR and also accepted a low under the zone when the pattern closed back in it)
  entry    : 'אות כניסה' = a WEEKLY pattern on the level whose last candle is one of the last `entry_weeks` (2) completed
             weeks, and price has not since closed under the pattern's low (daily patterns = a secondary confirmation)
Bars: completed weekly Mon-Fri bars and completed daily bars from the app's candle files (app/data/candles/<T>.json).
The zone gate is NOT applied in the file (app/data/confirm.json): the app applies it live with the zone that counts now
(his drawing, else the expert zone), like revc.json. `on_zone` is the Python twin, used for the expert watchlist and stats.

  python -m srs_app.confirm_patterns                 # rebuild app/data/confirm.json from the candle files (nightly: export)
  python -m srs_app.confirm_patterns --show ASB,JBL  # print the patterns of a few tickers
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from srs_app import expert_zone as E

RULE_VERSION = "confirm-v2-2026-11-16"
CONFIRM = {
    "prior_bars": 5,        # pullback: the pattern low is the lowest low of the 5 bars before it ...
    "decline_atr": 1.0,     # ... and >= 1 ATR(14) under their highest high
    "zone_tol_atr": 0.1,    # on the level: the pattern low inside [bottom - tol, top + tol], tol = min(0.1 ATR, 1% of the top)
    "zone_tol_pct": 0.01,   # (v2, Eyal 2026-11-16 NTRA: 0.5 ATR + 'closed back in the zone' let lows 16 points above the zone in)
    "entry_weeks": 2,       # entry signal: weekly pattern ending in the last 2 completed weeks, not broken since
    "keep_weeks": 8,        # weekly patterns stored (last candle within the last 8 completed weeks)
    "keep_days": 20,        # daily patterns stored (last candle within the last 20 completed sessions)
    "penetration": 0.3,     # TA-Lib default for the morning stars
}
# TA-Lib TA_CandleDefaultSettings: (range type, average period, factor)
SET = {"BodyLong": ("RealBody", 10, 1.0), "BodyShort": ("RealBody", 10, 1.0), "BodyDoji": ("HighLow", 10, 0.1),
       "Equal": ("HighLow", 5, 0.05)}
NAMES_HE = {"engulf": "בליעה שורית", "mstar": "כוכב בוקר", "mdoji": "כוכב בוקר דוג'י", "pierce": "קו חודר",
            "inside3": "שלושה מבפנים למעלה", "hammerc": "פטיש + נר אישור", "tweezer": "תחתית פינצטה"}
NBARS = {"engulf": 2, "mstar": 3, "mdoji": 3, "pierce": 2, "inside3": 3, "hammerc": 2, "tweezer": 2}
SRC = {"engulf": "TA-Lib CDLENGULFING; Nison", "mstar": "TA-Lib CDLMORNINGSTAR (penetration 0.3); Nison",
       "mdoji": "TA-Lib CDLMORNINGDOJISTAR (penetration 0.3); Nison", "pierce": "TA-Lib CDLPIERCING; Nison",
       "inside3": "TA-Lib CDL3INSIDE; Nison", "hammerc": "Investopedia: hammer confirmed by the next candle closing above the hammer's close",
       "tweezer": "Nison / Investopedia: tweezer bottom (matching lows, TA-Lib 'Equal' tolerance)",
       "pullback": "Nison / Bulkowski: a reversal pattern needs a prior decline (TA-Lib leaves the trend to the user)"}


# ---------------- TA-Lib candle primitives ----------------
def _rb(b) -> float:
    return abs(b["close"] - b["open"])


def _col(b) -> int:
    return 1 if b["close"] >= b["open"] else -1


def _range(kind: str, b) -> float:
    if kind == "RealBody":
        return _rb(b)
    if kind == "HighLow":
        return b["high"] - b["low"]
    return (b["high"] - max(b["open"], b["close"])) + (min(b["open"], b["close"]) - b["low"])  # Shadows


def _avg(B, setting: str, i: int) -> Optional[float]:
    """TA_CANDLEAVERAGE of `setting` for bar i: factor x mean range of the `period` bars before i (period 0 = bar i)."""
    kind, per, f = SET[setting]
    if per == 0:
        v = _range(kind, B[i])
    else:
        if i - per < 0:
            return None
        v = sum(_range(kind, B[j]) for j in range(i - per, i)) / per
    return f * v / (2.0 if kind == "Shadows" else 1.0)


def _gap_down(B, a: int, b: int) -> bool:
    """TA_REALBODYGAPDOWN(a, b): bar a's real body entirely under bar b's."""
    return max(B[a]["open"], B[a]["close"]) < min(B[b]["open"], B[b]["close"])


def _lt(x, y) -> bool:
    return y is not None and x < y


def _le(x, y) -> bool:
    return y is not None and x <= y


def _gt(x, y) -> bool:
    return y is not None and x > y


# ---------------- patterns (i = index of the LAST candle of the pattern) ----------------
def engulf(B, i: int) -> bool:
    """TA-Lib CDLENGULFING (bullish) + Nison: the engulfing white body is a real one (> TA-Lib BodyShort average)."""
    if i < 1:
        return False
    p, c = B[i - 1], B[i]
    return _col(c) == 1 and _col(p) == -1 and _gt(_rb(c), _avg(B, "BodyShort", i)) and (
        (c["close"] >= p["open"] and c["open"] < p["close"]) or (c["close"] > p["open"] and c["open"] <= p["close"]))


def _star(B, i: int, doji: bool) -> bool:
    if i < 2:
        return False
    pen = CONFIRM["penetration"]
    a, m, c = B[i - 2], B[i - 1], B[i]
    mid_ok = _le(_rb(m), _avg(B, "BodyDoji", i - 1)) if doji else _le(_rb(m), _avg(B, "BodyShort", i - 1))
    return (_gt(_rb(a), _avg(B, "BodyLong", i - 2)) and _col(a) == -1 and mid_ok and _gap_down(B, i - 1, i - 2)
            and _gt(_rb(c), _avg(B, "BodyShort", i)) and _col(c) == 1 and c["close"] > a["close"] + _rb(a) * pen)


def mstar(B, i: int) -> bool:
    return _star(B, i, False)


def mdoji(B, i: int) -> bool:
    return _star(B, i, True)


def pierce(B, i: int) -> bool:
    if i < 1:
        return False
    p, c = B[i - 1], B[i]
    return (_col(p) == -1 and _gt(_rb(p), _avg(B, "BodyLong", i - 1)) and _col(c) == 1
            and _gt(_rb(c), _avg(B, "BodyLong", i)) and c["open"] < p["low"] and c["close"] < p["open"]
            and c["close"] > p["close"] + _rb(p) * 0.5)


def inside3(B, i: int) -> bool:
    if i < 2:
        return False
    a, m, c = B[i - 2], B[i - 1], B[i]
    return (_gt(_rb(a), _avg(B, "BodyLong", i - 2)) and _le(_rb(m), _avg(B, "BodyShort", i - 1))
            and max(m["close"], m["open"]) < max(a["close"], a["open"]) and min(m["close"], m["open"]) > min(a["close"], a["open"])
            and _col(a) == -1 and _col(c) == 1 and c["close"] > a["open"])


def hammerc(B, i: int) -> bool:
    """Hammer ('H') confirmed by a white candle closing above the hammer's HIGH (StockCharts / Bulkowski confirmation;
    v1 used the hammer's close, Investopedia's looser wording)."""
    if i < 1:
        return False
    h, c = B[i - 1], B[i]
    return (E.hammer_shape(h["open"], h["high"], h["low"], h["close"]) == "H" and _col(c) == 1
            and c["close"] > c["open"] and c["close"] > h["high"])


def tweezer(B, i: int) -> bool:
    """Tweezer bottom: black then white with matching lows, and the white candle shows real buying (v2, Eyal 2026-11-16
    NTRA: a tiny white candle after a long black one is not a reversal): its body is not short (> TA-Lib BodyShort
    average) and it closes above the midpoint of the black body."""
    if i < 1:
        return False
    p, c = B[i - 1], B[i]
    return (_col(p) == -1 and p["close"] < p["open"] and _col(c) == 1 and c["close"] > c["open"]
            and _le(abs(c["low"] - p["low"]), _avg(B, "Equal", i - 1))
            and _gt(_rb(c), _avg(B, "BodyShort", i)) and c["close"] > (p["open"] + p["close"]) / 2)


PATTERNS = {"engulf": engulf, "mstar": mstar, "mdoji": mdoji, "pierce": pierce, "inside3": inside3,
            "hammerc": hammerc, "tweezer": tweezer}


def _atr_series(B) -> List[Optional[float]]:
    """Wilder ATR(14) at every bar (same recurrence as expert_zone.wilder_atr / the app's atr())."""
    n = E.ATR_N
    out: List[Optional[float]] = [None] * len(B)
    a = 0.0
    for i in range(1, len(B)):
        h, l, pc = B[i]["high"], B[i]["low"], B[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        a = a + tr / n if i <= n else (a * (n - 1) + tr) / n
        if i >= n:
            out[i] = a
    return out


def pullback(B, first: int, low: float, atr: Optional[float]) -> bool:
    """Prior decline into the pattern: its low is the lowest low of the `prior_bars` bars before its first candle and
    >= decline_atr x ATR under their highest high."""
    P = CONFIRM["prior_bars"]
    if first - P < 0 or not atr:
        return False
    prev = B[first - P:first]
    return low <= min(b["low"] for b in prev) and max(b["high"] for b in prev) - low >= CONFIRM["decline_atr"] * atr


def detect(B: Sequence[Dict[str, Any]], keep: int) -> List[Dict[str, Any]]:
    """Every pattern (after a pullback) whose last candle is among the last `keep` bars of B (B = completed bars, oldest
    first). k = bars back of the last candle (0 = the last completed bar). Newest first."""
    A = _atr_series(B)
    n, out = len(B), []
    for i in range(n - 1, max(-1, n - 1 - keep), -1):
        for code, fn in PATTERNS.items():
            try:
                hit = fn(B, i)
            except (KeyError, TypeError, ZeroDivisionError):
                hit = False
            if not hit or (code == "mstar" and mdoji(B, i)):   # a doji star is reported once, as the doji variant
                continue
            f = i - NBARS[code] + 1
            lo = min(b["low"] for b in B[f:i + 1])
            a = A[i] or A[i - 1] if i >= 1 else None
            if not pullback(B, f, lo, a):
                continue
            out.append({"p": code, "k": n - 1 - i, "s": B[f]["time"], "e": B[i]["time"], "lo": round(lo, 4),
                        "hi": round(max(b["high"] for b in B[f:i + 1]), 4), "c": round(B[i]["close"], 4),
                        "a": round(a, 4)})
    return out


def zone_tol(p: Dict[str, Any], top: float) -> float:
    return min(CONFIRM["zone_tol_atr"] * p["a"], CONFIRM["zone_tol_pct"] * abs(top))


def on_zone(p: Dict[str, Any], top: float, bot: float) -> bool:
    """The pattern's low actually touches the zone: bottom - tol <= low <= top + tol (module doc 'on level')."""
    top, bot = max(top, bot), min(top, bot)
    t = zone_tol(p, top)
    return bot - t <= p["lo"] <= top + t


def is_entry(p: Dict[str, Any], weekly: bool, closes_after: Sequence[float]) -> bool:
    """Entry signal: a weekly pattern ending in the last entry_weeks completed weeks, no close under its low since."""
    return weekly and p["k"] < CONFIRM["entry_weeks"] and all(c >= p["lo"] for c in closes_after)


# ---------------- bars from the app candle files ----------------
def _bar(r) -> Dict[str, Any]:
    return {"time": str(r[0])[:10], "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])}


def completed_daily(rows: Sequence[Sequence[Any]], now_ny: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Daily bars, without today's session while New York is still trading (before 16:15 ET)."""
    B = [_bar(r) for r in rows]
    if B:
        try:
            from zoneinfo import ZoneInfo
            ny = now_ny or datetime.now(ZoneInfo("America/New_York"))
            if B[-1]["time"] == ny.date().isoformat() and (ny.hour, ny.minute) < (16, 15):
                B = B[:-1]
        except Exception:
            pass
    return B


def completed_weekly(rows: Sequence[Sequence[Any]], asof: Optional[str] = None) -> List[Dict[str, Any]]:
    W = E.weekly(rows)
    if W and not E.week_complete(W[-1]["last"], asof):
        W = W[:-1]
    return [{"time": w["time"], "open": w["open"], "high": w["high"], "low": w["low"], "close": w["close"], "last": w["last"]} for w in W]


def of_rows(rows: Sequence[Sequence[Any]], asof: Optional[str] = None, now_ny: Optional[datetime] = None) -> Dict[str, Any]:
    """{'w': [...], 'd': [...], 'lw': last completed week (Monday), 'ld': last completed session, 'px': last close}"""
    W = completed_weekly(rows, asof)
    D = completed_daily(rows, now_ny)
    return {"w": detect(W, CONFIRM["keep_weeks"]), "d": detect(D, CONFIRM["keep_days"]),
            "lw": W[-1]["time"] if W else None, "ld": D[-1]["time"] if D else None,
            "px": float(rows[-1][4]) if rows else None,
            # closes after each weekly pattern (entry check) = completed weekly closes + the running price
            "wc": [round(w["close"], 4) for w in W[-CONFIRM["keep_weeks"]:]]}


def on_level(c: Dict[str, Any], top: float, bot: float) -> Dict[str, Any]:
    """Patterns of one ticker on a zone: {'w': [...+entry], 'd': [...], 'entry': bool}."""
    wc, px = c.get("wc") or [], c.get("px")
    ws = []
    for p in c.get("w") or []:
        if on_zone(p, top, bot):
            after = wc[len(wc) - p["k"]:] if p["k"] else []
            ws.append(dict(p, entry=is_entry(p, True, after + ([px] if px is not None else []))))
    ds = [p for p in c.get("d") or [] if on_zone(p, top, bot)]
    return {"w": ws, "d": ds, "entry": any(p["entry"] for p in ws)}


def build(data_dir: Path, asof: Optional[str] = None, tickers: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    cdir = data_dir / "candles"
    ts = sorted(tickers) if tickers else sorted(f.stem for f in cdir.glob("*.json"))
    out: Dict[str, Any] = {}
    for t in ts:
        f = cdir / f"{t}.json"
        if not f.exists():
            continue
        try:
            c = of_rows(json.loads(f.read_text())["d"], asof)
        except Exception as e:  # never block the export
            print(f"  [confirm] {t}: {e}")
            continue
        if c["w"] or c["d"]:
            out[t] = c
    return out


def write(data_dir: Path, asof: Optional[str] = None) -> Path:
    doc = {"rule_version": RULE_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "asof": asof or date.today().isoformat(), "consts": CONFIRM, "names": NAMES_HE, "sources": SRC,
           "tickers": build(data_dir, asof)}
    p = data_dir / "confirm.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).resolve().parent.parent / "app" / "data"))
    ap.add_argument("--asof", default=None)
    ap.add_argument("--show", default="")
    a = ap.parse_args(argv)
    d = Path(a.data)
    if a.show:
        ez = json.loads((d / "expert_zones.json").read_text())["tickers"] if (d / "expert_zones.json").exists() else {}
        for t in [x.strip().upper() for x in a.show.split(",") if x.strip()]:
            c = build(d, a.asof, [t]).get(t) or {"w": [], "d": []}
            z = ez.get(t) or {}
            lv = on_level(c, z["top"], z["bottom"]) if z.get("ok") else None
            print(t, "zone", (z.get("bottom"), z.get("top")) if z.get("ok") else None)
            for tf in ("w", "d"):
                for p in c[tf]:
                    print(f"  {tf} {p['e']} {NAMES_HE[p['p']]} ({p['p']}) k={p['k']} low={p['lo']}"
                          + (f" on-level={'yes' if on_zone(p, z['top'], z['bottom']) else 'no'}" if lv else ""))
            if lv:
                print("  entry signal:", lv["entry"])
        return
    p = write(d, a.asof)
    doc = json.loads(p.read_text())
    print(f"confirm patterns: {len(doc['tickers'])} tickers with a pattern after a pullback -> {p}")


if __name__ == "__main__":
    main()
