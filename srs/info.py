"""Stock info (stub): inst own %, short float %, sector, industry, market cap, next earnings.

Source order mirrors stock_screen.py: FinViz quote page first (the same 'Inst Own' / 'Short Float'
snapshot cells stock_screen.scrape_finviz_fundamentals reads), yfinance as fallback. Not cached
and not used by any pure function; network required.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Optional

import requests

from .data import yf_symbol

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")


def _pct(txt: Optional[str]) -> Optional[float]:
    if not txt:
        return None
    t = txt.replace("%", "").strip()
    try:
        return float(t) / 100.0
    except ValueError:
        return None


def _cap(txt: Optional[str]) -> Optional[float]:
    m = re.match(r"^([\d.]+)\s*([KMBT]?)$", (txt or "").strip())
    if not m:
        return None
    return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2)]


def _earn(txt: Optional[str], today: date) -> Optional[str]:
    """FinViz 'Oct 28 AMC' -> ISO date. FinViz shows the NEXT report when scheduled, else the LAST
    one; a date in the past (or > 120 days ahead) is therefore not a next-earnings date -> None."""
    m = re.match(r"^([A-Z][a-z]{2})\s+(\d{1,2})", (txt or "").strip())
    if not m:
        return None
    for yr in (today.year, today.year + 1):
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2)} {yr}", "%b %d %Y").date()
        except ValueError:
            return None
        if 0 <= (d - today).days <= 120:
            return d.isoformat()
    return None


def finviz_snapshot(ticker: str, timeout: int = 20) -> Dict[str, str]:
    """All FinViz snapshot label -> value pairs + sector/industry (raw strings)."""
    from bs4 import BeautifulSoup
    t = yf_symbol(ticker)
    r = requests.get(f"https://finviz.com/quote.ashx?t={t}&p=d", timeout=timeout,
                     headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    out: Dict[str, str] = {}
    cells = soup.select("table.snapshot-table2 td")
    for a, b in zip(cells[0::2], cells[1::2]):
        out[a.get_text(strip=True)] = b.get_text(strip=True)
    links = [a.get_text(strip=True) for a in soup.select("div.quote-links a.tab-link")]
    if len(links) >= 2:
        out["_sector"], out["_industry"] = links[0], links[1]
    return out


def info(ticker: str, today: Optional[date] = None) -> Dict[str, Any]:
    """{'ticker', 'inst_own', 'short_float', 'sector', 'industry', 'market_cap', 'next_earnings',
    'source', 'errors'}; fractions (0.85 = 85%); None = not available."""
    today = today or date.today()
    out: Dict[str, Any] = {"ticker": yf_symbol(ticker), "inst_own": None, "short_float": None,
                           "sector": None, "industry": None, "market_cap": None,
                           "next_earnings": None, "source": {}, "errors": []}
    try:
        s = finviz_snapshot(ticker)
        vals = {"inst_own": _pct(s.get("Inst Own")), "short_float": _pct(s.get("Short Float")),
                "sector": s.get("_sector"), "industry": s.get("_industry"),
                "market_cap": _cap(s.get("Market Cap")), "next_earnings": _earn(s.get("Earnings"), today)}
        for k, v in vals.items():
            if v is not None:
                out[k], out["source"][k] = v, "finviz"
    except Exception as e:
        out["errors"].append(f"finviz: {e}")
    if any(out[k] is None for k in ("inst_own", "short_float", "sector", "market_cap", "next_earnings")):
        try:
            import yfinance as yf
            tk = yf.Ticker(out["ticker"])
            inf = tk.info or {}
            yv = {"inst_own": inf.get("heldPercentInstitutions"), "short_float": inf.get("shortPercentOfFloat"),
                  "sector": inf.get("sector"), "industry": inf.get("industry"), "market_cap": inf.get("marketCap")}
            try:
                cal = tk.calendar or {}
                ed = [d for d in (cal.get("Earnings Date") or []) if isinstance(d, date) and d >= today]
                yv["next_earnings"] = min(ed).isoformat() if ed else None
            except Exception:
                pass
            for k, v in yv.items():
                if out.get(k) is None and v is not None:
                    out[k], out["source"][k] = v, "yfinance"
        except Exception as e:
            out["errors"].append(f"yfinance: {e}")
    return out
