"""Past (and next) earnings report dates per app ticker for the chart 'E' markers (Eyal 2026-10-28:
"add markers on the chart with the past report dates").

app/data/earnings.json = {TICKER: {"p": [{"d": "YYYY-MM-DD", "t": "bmo"|"amc"|None, "e": est|None, "a": actual|None,
                                          "s": surprise %|None}, ...oldest first],
                                   "n": next date|None, "ne": next date is an estimate (bool), "src": "yahoo"|"cache"}}

Source: yfinance get_earnings_dates (Yahoo calendar: date, time -> BMO/AMC, EPS estimate / reported / surprise),
cached in cache/earnmarks_{T}.json. Never invented: a value Yahoo does not give stays null. When Yahoo has nothing
(or times out) the dates alone come from the scanner caches (earnhist_{T}.json, earn_{T}.json last_earnings_date).
Funds / ETFs (stock_screen.is_fund, cache only) have no earnings and are skipped (no network). Every Yahoo call is
wall-clock bounded (stock_screen._bounded_call) and a breaker stops asking after BREAKER consecutive timeouts in a run
(the 2026-10-27 nightly stalled for hours inside the same yfinance call).

Refresh: a cache is reused for TTL_DAYS, except that it is re-fetched (once a day at most) when a report date it
knew as upcoming (or the scanner's next date) has passed since the fetch, so the new actual EPS shows up the night
after the report. Failures are retried after a day.
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

TTL_DAYS = 30
CALL_TIMEOUT_S = 25
BREAKER = 3
LIMIT = 28          # quarters asked from Yahoo (~6-7 years incl. the upcoming ones; the chart has 5 years)
WORKERS = 4
_TIMEOUTS = [0]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, 4)


def _timing(ts: Any) -> Optional[str]:
    """Yahoo's report time (America/New_York) -> 'bmo' (before 09:30) / 'amc' (16:00 or later); midnight or a
    mid-session time = unknown (None)."""
    try:
        h, m = int(ts.hour), int(ts.minute)
    except Exception:
        return None
    if h == 0 and m == 0:
        return None
    if (h, m) < (9, 30):
        return "bmo"
    if h >= 16:
        return "amc"
    return None


def rows_from_frame(df: Any) -> List[Dict[str, Any]]:
    """get_earnings_dates DataFrame -> [{d, t, e, a, s}] sorted by date (one row per date, the richest kept)."""
    out: Dict[str, Dict[str, Any]] = {}
    if df is None or not len(df):
        return []
    cols = {str(c).lower(): c for c in df.columns}
    ce = next((cols[k] for k in cols if "estimate" in k), None)
    ca = next((cols[k] for k in cols if "reported" in k), None)
    cs = next((cols[k] for k in cols if "surprise" in k), None)
    for ts, r in df.iterrows():
        try:
            d = str(ts.date())
        except Exception:
            continue
        row = {"d": d, "t": _timing(ts), "e": _num(r[ce]) if ce is not None else None,
               "a": _num(r[ca]) if ca is not None else None, "s": _num(r[cs]) if cs is not None else None}
        old = out.get(d)
        if old is None or sum(v is not None for v in row.values()) > sum(v is not None for v in old.values()):
            out[d] = row
    return [out[k] for k in sorted(out)]


def _yahoo_fetch(ticker: str):
    import yfinance as yf
    return yf.Ticker(ticker.replace(".", "-")).get_earnings_dates(limit=LIMIT)


def _cache_path(cache_dir: Path, t: str) -> Path:
    return cache_dir / f"earnmarks_{t.upper()}.json"


def _age_days(iso: Any) -> float:
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    except Exception:
        return 1e9


def _needs_refresh(c: Optional[Dict[str, Any]], today: date, next_hint: Optional[str]) -> bool:
    if not c:
        return True
    age = _age_days(c.get("fetched_at"))
    if c.get("rows") is None:            # failure / nothing from Yahoo: retried after a day
        return age >= 1
    if age >= TTL_DAYS:
        return True
    fetched = str(c.get("fetched_at", ""))[:10]
    t = today.isoformat()
    upcoming = [r["d"] for r in c["rows"] if r.get("a") is None and r["d"] >= fetched]
    if next_hint:
        upcoming.append(next_hint[:10])
    # a report that was still upcoming at fetch time is now past -> fetch its actual (at most once a day)
    return age >= 1 and any(fetched <= d < t for d in upcoming)


def fallback_dates(t: str, cache_dir: Path) -> List[str]:
    """Past report dates already in the scanner caches (no EPS): earnhist_{T}.json + earn_{T}.json last date."""
    ds: set = set()
    try:
        ds.update(json.loads((cache_dir / f"earnhist_{t}.json").read_text()).get("dates") or [])
    except Exception:
        pass
    try:
        e = json.loads((cache_dir / f"earn_{t}.json").read_text())
        if e.get("last_earnings_date"):
            ds.add(str(e["last_earnings_date"])[:10])
    except Exception:
        pass
    return sorted(ds)


def ticker_marks(t: str, today: date, cache_dir: Path, next_date: Optional[str] = None, next_est: bool = False,
                 since: Optional[str] = None, fetch: Optional[Callable[[str], Any]] = None,
                 bounded: Optional[Callable[..., Any]] = None) -> Optional[Dict[str, Any]]:
    """Marker entry for one (non-fund) ticker, or None when no past report date is known at all."""
    cf = _cache_path(cache_dir, t)
    try:
        c = json.loads(cf.read_text()) if cf.exists() else None
    except Exception:
        c = None
    if _needs_refresh(c, today, next_date) and _TIMEOUTS[0] < BREAKER:
        fetch = fetch or _yahoo_fetch
        rows, note = None, ""
        try:
            df = bounded(fetch, CALL_TIMEOUT_S, t) if bounded else fetch(t)
            _TIMEOUTS[0] = 0
            rows = rows_from_frame(df) or None
            note = "" if rows else "no earnings dates from Yahoo"
        except TimeoutError as e:
            _TIMEOUTS[0] += 1
            note = f"timeout: {str(e)[:60]}"
        except Exception as e:
            note = f"error: {str(e)[:80]}"
            if "timed out" in str(e).lower():
                _TIMEOUTS[0] += 1
        if rows is not None or not (c and c.get("rows")):  # a failed refresh keeps the older good rows
            c = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows, "note": note}
            try:
                cf.write_text(json.dumps(c, separators=(",", ":")))
            except Exception:
                pass
    tday = today.isoformat()
    rows = (c or {}).get("rows") or []
    src = "yahoo"
    past = [r for r in rows if r["d"] <= tday and (r["d"] < tday or r.get("a") is not None)]
    if not past:
        src = "cache"
        past = [{"d": d, "t": None, "e": None, "a": None, "s": None} for d in fallback_dates(t, cache_dir) if d < tday]
    if since:
        past = [r for r in past if r["d"] >= since]
    nxt, ne = (next_date[:10], bool(next_est)) if next_date and str(next_date)[:10] >= tday else (None, False)
    if nxt is None:  # Yahoo's own upcoming date (no actual yet), within ~6 months
        fut = [r["d"] for r in rows if r["d"] >= tday and r.get("a") is None and r["d"] <= (today + timedelta(days=190)).isoformat()]
        if fut:
            nxt, ne = fut[0], True
    if not past and not nxt:
        return None
    out: Dict[str, Any] = {"p": [{k: r.get(k) for k in ("d", "t", "e", "a", "s")} for r in past], "n": nxt, "ne": ne, "src": src}
    nr = next((r for r in rows if r["d"] == nxt), None)
    if nr:
        out["nt"], out["nest"] = nr.get("t"), nr.get("e")
    return out


def build(rows: Iterable[Dict[str, Any]], tickers: Iterable[str], cache_dir: Path, is_fund: Callable[[str], bool],
          today: Optional[date] = None, since: Optional[str] = None, fetch=None, bounded=None,
          workers: int = WORKERS) -> Dict[str, Any]:
    """earnings.json payload for `tickers` (funds skipped). rows give the scanner's next date (earnings_date /
    earnings_estimated) per ticker."""
    today = today or date.today()
    by = {str(r.get("ticker")): r for r in rows}
    todo = [t for t in sorted(set(tickers)) if not is_fund(t)]
    _TIMEOUTS[0] = 0

    def one(t: str):
        r = by.get(t) or {}
        ed = r.get("earnings_date")
        ed = str(ed)[:10] if isinstance(ed, str) and ed[:4].isdigit() else None
        try:
            return t, ticker_marks(t, today, cache_dir, ed, bool(r.get("earnings_estimated")), since, fetch, bounded)
        except Exception as e:  # never block the export
            print(f"  [earnings marks] {t}: {e}")
            return t, None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        res = dict(ex.map(one, todo))
    return {t: v for t, v in sorted(res.items()) if v}
