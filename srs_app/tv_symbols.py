"""TradingView symbol (EXCHANGE:SYMBOL) per ticker, for the app's copy button (Eyal 2026-10-27: "copy the ticker with
its exchange in a format that can be pasted into TradingView").

Source of truth = TradingView's own scanner (scanner.tradingview.com/america/scan, public, no login): its row id `s` is
exactly the symbol TradingView uses (NASDAQ:SNX, NYSE:BRK.B, AMEX:SPY for NYSE Arca ETFs, CBOE:/BATS: for Cboe BZX ...).
When a ticker has several US rows the primary listing on a US exchange wins; OTC is never used.
Fallbacks (scanner down / ticker unknown): the exchange already in the report's tradingview_url (FinViz / yfinance, see
stock_screen._map_exchange_to_tv), else None (the app then copies the plain ticker).

Class shares: TradingView writes them with a dot (BRK-B / BRK/B / BRK.B -> BRK.B, CRD-A -> CRD.A).

Cache: /workspace/cache/tv_symbols.json (hits 30 days, misses 3 days); SRS_NO_NET=1 disables fetching.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

CACHE = Path(os.environ.get("SRS_TV_SYMBOL_CACHE", "/workspace/cache/tv_symbols.json"))
HIT_TTL_DAYS = 30
MISS_TTL_DAYS = 3
SCAN_URL = "https://scanner.tradingview.com/america/scan"
US_EXCHANGES = ("NASDAQ", "NYSE", "AMEX", "CBOE", "BATS")   # preference order when nothing is marked primary
FALLBACK_EX = {"NASDAQ", "NYSE", "AMEX", "CBOE", "BATS", "NYSEARCA", "ARCA", "NYSEAMERICAN"}
_EX_ALIAS = {"NYSEARCA": "AMEX", "ARCA": "AMEX", "NYSEAMERICAN": "AMEX"}


def tv_name(ticker: str) -> str:
    """Ticker as TradingView writes it: upper case, class-share separator '-' or '/' -> '.' (BRK-B -> BRK.B)."""
    return re.sub(r"[-/]", ".", str(ticker or "").strip().upper())


def pick(cands: Iterable[Dict[str, Any]]) -> Optional[str]:
    """Best TradingView symbol among scanner rows {'s': 'EX:NAME', 'exchange', 'is_primary'}: US exchanges only,
    primary listing first, then US_EXCHANGES order."""
    us = [c for c in cands if str(c.get("exchange") or "").upper() in US_EXCHANGES and c.get("s")]
    if not us:
        return None
    us.sort(key=lambda c: (not c.get("is_primary"), US_EXCHANGES.index(str(c["exchange"]).upper())))
    return us[0]["s"]


def from_url(url: Any, ticker: str) -> Optional[str]:
    """EXCHANGE:NAME from a report tradingview_url (…?symbol=NYSE:PNC); None if it has no known exchange."""
    m = re.search(r"symbol=([A-Za-z]+)(?::|%3A)([^&]+)", str(url or ""))
    if not m:
        return None
    ex = m.group(1).upper()
    if ex not in FALLBACK_EX:
        return None
    return f"{_EX_ALIAS.get(ex, ex)}:{tv_name(ticker)}"


def fetch_scanner(names: List[str], post: Optional[Callable[..., Any]] = None, batch: int = 400) -> Dict[str, List[Dict[str, Any]]]:
    """{NAME: [scanner rows]} for TradingView names, in batches."""
    if post is None:
        import requests
        post = lambda body: requests.post(SCAN_URL, json=body, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).json()  # noqa: E731
    out: Dict[str, List[Dict[str, Any]]] = {}
    for i in range(0, len(names), batch):
        part = names[i:i + batch]
        body = {"filter": [{"left": "name", "operation": "in_range", "right": part}],
                "columns": ["name", "exchange", "type", "is_primary"], "range": [0, len(part) * 4]}
        try:
            res = post(body) or {}
        except Exception as e:
            print(f"  [tv symbols] scanner failed: {e}")
            continue
        for d in res.get("data") or []:
            name, ex, typ, prim = (d.get("d") or [None] * 4)[:4]
            out.setdefault(str(name).upper(), []).append({"s": d.get("s"), "exchange": ex, "type": typ, "is_primary": prim})
    return out


def attach_tv_symbols(rows: List[Dict[str, Any]], cache_path: Optional[Path] = None,
                      fetch: Optional[Callable[[List[str]], Dict[str, List[Dict[str, Any]]]]] = None,
                      now: Optional[datetime] = None) -> int:
    """row['tv_symbol'] = 'EXCHANGE:NAME' (None = unknown). Scanner (cached) > report tradingview_url. Returns #fetched."""
    cache_path = cache_path or CACHE
    fetch = fetch or (None if os.environ.get("SRS_NO_NET") else fetch_scanner)
    now = now or datetime.now(timezone.utc)
    try:
        cache: Dict[str, Any] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except Exception:
        cache = {}

    def fresh(e: Dict[str, Any]) -> bool:
        try:
            age = (now - datetime.fromisoformat(e["fetched"])).days
        except Exception:
            return False
        return age < (HIT_TTL_DAYS if e.get("s") else MISS_TTL_DAYS)

    need = sorted({tv_name(r["ticker"]) for r in rows if not (cache.get(tv_name(r["ticker"])) and fresh(cache[tv_name(r["ticker"])]))})
    n = 0
    if fetch and need:
        got = fetch(need)
        if got:  # an empty answer = scanner down: keep the old cache entries
            for name in need:
                cache[name] = {"s": pick(got.get(name, [])), "fetched": now.isoformat(timespec="seconds")}
            n = len(need)
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(cache, indent=0, sort_keys=True))
            except Exception as ex:
                print(f"  [tv symbols] cache write failed: {ex}")
    for r in rows:
        name = tv_name(r["ticker"])
        r["tv_symbol"] = (cache.get(name) or {}).get("s") or from_url(r.get("tradingview_url"), r["ticker"])
    return n
