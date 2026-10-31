"""Institutional ownership % and short float % per app list row (Eyal 2026-10-31: "show next to each stock its
institutional % and short float %").

Sources, in order:
  1. the report row itself (inst_own_pct / short_float_pct from historical-reports/latest.csv);
  2. the nightly FinViz screener bulk (v=131 'Inst Own' / 'Short Float' for the whole universe,
     /workspace/cache/fv_ownership.json, written by stock_screen.fetch_screener_tickers);
  3. for tickers outside the universe (watchlist / his drawings / positions rows, status OUT): the FinViz quote
     page, cached per ticker in /workspace/cache/ownership_quote.json (hits OWN_TTL_DAYS, misses OWN_MISS_TTL_DAYS).

Funds / ETFs have no values on FinViz ('-'): they stay None and the app shows '—'. Missing values never filter a row.
Fetching is bounded like the Yahoo earnings guard: at most max_fetch quote pages, a wall-clock budget, and a breaker
after `breaker` consecutive failures (403 / 429 / timeouts) - the export never stalls on FinViz. SRS_NO_NET=1 disables it.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

BULK = Path(os.environ.get("SRS_OWNERSHIP_JSON", "/workspace/cache/fv_ownership.json"))
QUOTE_CACHE = Path(os.environ.get("SRS_OWNERSHIP_CACHE", "/workspace/cache/ownership_quote.json"))
OWN_TTL_DAYS = 7
OWN_MISS_TTL_DAYS = 14


def _pct_num(v: Any) -> Optional[float]:
    """'72.3%' / 0.723 (fraction) -> 72.3; None / '-' -> None."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.replace("%", "").replace(",", "").strip()
        if not s or s == "-":
            return None
        try:
            return round(float(s), 2)
        except ValueError:
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return round(f * 100.0, 2)


def fetch_quote(ticker: str) -> Dict[str, Any]:
    """{'inst_own_pct', 'short_float_pct'} (percent numbers or None) from the FinViz quote page."""
    from srs.info import finviz_snapshot
    s = finviz_snapshot(ticker, timeout=15)
    return {"inst_own_pct": _pct_num(s.get("Inst Own")), "short_float_pct": _pct_num(s.get("Short Float"))}


def load_bulk(path: Optional[Path] = None) -> Dict[str, Any]:
    try:
        j = json.loads((path or BULK).read_text())
        return {"fetched_at": j.get("fetched_at"), "tickers": j.get("tickers") or {}}
    except Exception:
        return {"fetched_at": None, "tickers": {}}


def _age_days(iso: Any, now: datetime) -> float:
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 86400.0
    except Exception:
        return 1e9


def attach_ownership(rows: List[Dict[str, Any]], bulk: Optional[Dict[str, Any]] = None, cache_path: Optional[Path] = None,
                     fetch: Optional[Callable[[str], Dict[str, Any]]] = None, now: Optional[datetime] = None,
                     max_fetch: int = 150, budget_s: float = 120.0, breaker: int = 5, sleep_s: float = 0.35) -> Dict[str, int]:
    """Fill row['inst_own_pct'] / row['short_float_pct'] (percent, None = unknown) and row['own_date'] (YYYY-MM-DD of
    the source). Returns counters {'fetched', 'failed', 'inst', 'short', 'rows', 'tripped'}."""
    cache_path = cache_path or QUOTE_CACHE
    if fetch is None and not os.environ.get("SRS_NO_NET"):
        fetch = fetch_quote
    now = now or datetime.now(timezone.utc)
    bulk = bulk if bulk is not None else load_bulk()
    bt = bulk.get("tickers") or {}
    bdate = str(bulk.get("fetched_at") or "")[:10] or None
    try:
        cache: Dict[str, Any] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except Exception:
        cache = {}
    st = {"fetched": 0, "failed": 0, "inst": 0, "short": 0, "rows": len(rows), "tripped": 0}
    t0 = time.monotonic()
    consecutive = 0
    for r in rows:
        t = str(r["ticker"]).upper()
        inst, short = r.get("inst_own_pct"), r.get("short_float_pct")
        src_date = r.get("own_date")
        if t in bt:  # bulk (screener universe): authoritative for this run, including ETFs with '-'
            b = bt[t] or {}
            inst = inst if inst is not None else _pct_num(b.get("inst_own"))
            short = short if short is not None else _pct_num(b.get("short_float"))
            src_date = src_date or bdate
        elif inst is None and short is None:  # outside the universe: per-ticker quote cache
            e = cache.get(t)
            stale = e is None or _age_days(e.get("fetched"), now) >= (
                OWN_TTL_DAYS if (e.get("inst_own_pct") is not None or e.get("short_float_pct") is not None) else OWN_MISS_TTL_DAYS)
            can = fetch is not None and not st["tripped"] and st["fetched"] + st["failed"] < max_fetch
            if stale and can and time.monotonic() - t0 > budget_s:
                st["tripped"] = 1
                print(f"  [ownership] FinViz quote budget {budget_s:.0f}s spent - the rest keep cached values")
                can = False
            if stale and can:
                try:
                    got = fetch(t) or {}
                    e = {"inst_own_pct": got.get("inst_own_pct"), "short_float_pct": got.get("short_float_pct"),
                         "fetched": now.isoformat(timespec="seconds")}
                    cache[t] = e
                    st["fetched"] += 1
                    consecutive = 0
                except Exception as ex:
                    st["failed"] += 1
                    consecutive += 1
                    print(f"  [ownership] {t}: {ex}")
                    if consecutive >= breaker:
                        st["tripped"] = 1
                        print(f"  [ownership] {breaker} FinViz failures in a row - no more quote pages this run")
                if sleep_s and fetch is fetch_quote:
                    time.sleep(sleep_s)
            if e:
                inst, short = e.get("inst_own_pct"), e.get("short_float_pct")
                src_date = str(e.get("fetched") or "")[:10] or None
        r["inst_own_pct"] = _pct_num(inst) if isinstance(inst, str) else (None if inst is None else round(float(inst), 2))
        r["short_float_pct"] = _pct_num(short) if isinstance(short, str) else (None if short is None else round(float(short), 2))
        r["own_date"] = src_date if (r["inst_own_pct"] is not None or r["short_float_pct"] is not None) else None
        st["inst"] += r["inst_own_pct"] is not None
        st["short"] += r["short_float_pct"] is not None
    if st["fetched"]:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=0, sort_keys=True))
        except Exception as ex:
            print(f"  [ownership] cache write failed: {ex}")
    return st
