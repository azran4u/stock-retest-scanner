"""Daily OHLCV download + per-ticker CSV cache (yfinance, auto_adjust=True like stock_screen.py)."""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from .weekly import OHLCV, normalize_daily

DEFAULT_CACHE = Path("~/.srs_cache").expanduser()
OVERLAP_DAYS = 7          # incremental fetch re-downloads this many calendar days
ADJ_TOL = 0.002           # overlap closes differing > 0.2% => adjustment changed => full refetch


def yf_symbol(raw: str) -> str:
    """'NYSE:MOG.A' -> 'MOG-A', 'brk.b' -> 'BRK-B' (Yahoo uses '-' for share classes)."""
    t = raw.strip().upper()
    if ":" in t:
        t = t.split(":", 1)[1]
    return t.replace(".", "-").replace("/", "-")


def parse_tickers_file(path: str | Path) -> List[str]:
    """One ticker per line (or comma separated, like TradingView exports); EXCHANGE:TICKER ok;
    '#' starts a comment; blank lines and '###SECTION' headers ignored. Order kept, de-duplicated."""
    out: List[str] = []
    for line in Path(path).expanduser().read_text().splitlines():
        line = line.split("#", 1)[0]
        for tok in re.split(r"[,\s]+", line):
            if tok and not tok.startswith("###"):
                s = yf_symbol(tok)
                if s and s not in out:
                    out.append(s)
    return out


def cache_path(ticker: str, cache_dir: Path | str = DEFAULT_CACHE) -> Path:
    return Path(cache_dir).expanduser() / f"{yf_symbol(ticker)}.csv"


def load_cached(ticker: str, cache_dir: Path | str = DEFAULT_CACHE) -> Optional[pd.DataFrame]:
    p = cache_path(ticker, cache_dir)
    if not p.exists():
        return None
    d = pd.read_csv(p, index_col="Date", parse_dates=["Date"])
    return normalize_daily(d) if len(d) else None


def save_cached(ticker: str, df: pd.DataFrame, cache_dir: Path | str = DEFAULT_CACHE) -> Path:
    p = cache_path(ticker, cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    normalize_daily(df).to_csv(p, float_format="%.6f", date_format="%Y-%m-%d")
    return p


def _meta_path(cache_dir) -> Path:
    return Path(cache_dir).expanduser() / "_meta.json"


def _load_meta(cache_dir) -> Dict[str, dict]:
    import json
    try:
        return json.loads(_meta_path(cache_dir).read_text())
    except Exception:
        return {}


def _save_meta(cache_dir, meta: Dict[str, dict]) -> None:
    import json
    p = _meta_path(cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=0, sort_keys=True))


def _download(symbols: List[str], start: Optional[str] = None, period: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    """One yfinance batch call (same settings as stock_screen.download_batch)."""
    import yfinance as yf
    kw = dict(tickers=symbols, interval="1d", group_by="ticker", auto_adjust=True,
              threads=True, progress=False)
    if start:
        kw["start"] = start
    else:
        kw["period"] = period or "5y"
    data = yf.download(**kw)
    out: Dict[str, pd.DataFrame] = {}
    if data is None or data.empty:
        return out
    for s in symbols:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if s not in set(data.columns.get_level_values(0)):
                    continue
                df = data[s]
            else:
                df = data
            df = df.dropna(how="all")
            df = df.dropna(subset=["Close"]) if "Close" in df else df
            if not df.empty:
                out[s] = normalize_daily(df)
        except Exception:
            continue
    return out


@dataclass
class FetchResult:
    ok: List[str] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)
    full: List[str] = field(default_factory=list)       # fully (re)downloaded
    updated: List[str] = field(default_factory=list)    # incremental append
    fresh: List[str] = field(default_factory=list)      # already up to date

    def summary(self) -> str:
        s = (f"{len(self.ok)} ok ({len(self.full)} full download, {len(self.updated)} updated, "
             f"{len(self.fresh)} already fresh), {len(self.failed)} failed")
        if self.failed:
            s += "\nfailed: " + ", ".join(f"{t} ({why})" for t, why in self.failed.items())
        return s


def _last_weekday(today: date) -> date:
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fetch_many(tickers: Iterable[str], years: int = 5, cache_dir: Path | str = DEFAULT_CACHE,
               chunk: int = 50, today: Optional[date] = None, log=print) -> FetchResult:
    """Make the cache hold >= `years` of daily bars through the latest session for every ticker.
    Missing / too-short caches are downloaded in full; others get only the missing days (plus an
    OVERLAP_DAYS overlap that replaces the tail, so a partial intraday bar is corrected). If the
    overlap disagrees with the cache (a dividend/split changed the adjustment), refetch in full."""
    today = today or date.today()
    target = _last_weekday(today)
    need_start = pd.Timestamp(today) - pd.DateOffset(years=years) + pd.Timedelta(days=7)
    res = FetchResult()
    syms = list(dict.fromkeys(yf_symbol(t) for t in tickers))
    full: List[str] = []
    incr: Dict[str, List[str]] = {}
    cached: Dict[str, pd.DataFrame] = {}
    meta = _load_meta(cache_dir)  # {ticker: {"years": N}} = longest history already requested
    for s in syms:
        df = load_cached(s, cache_dir)
        short = df is not None and len(df) and df.index[0] > need_start
        if df is None or df.empty or (short and meta.get(s, {}).get("years", 0) < years):
            full.append(s)
            continue
        cached[s] = df
        if df.index[-1].date() >= target:
            res.ok.append(s); res.fresh.append(s)
            continue
        start = (df.index[-1] - pd.Timedelta(days=OVERLAP_DAYS)).strftime("%Y-%m-%d")
        incr.setdefault(start, []).append(s)

    def _full(batch: List[str]):
        got = {}
        try:
            got = _download(batch, period=f"{years}y")
        except Exception as e:  # pragma: no cover - network
            log(f"[fetch] batch error: {e}")
        for s in batch:
            if s in got and len(got[s]):
                save_cached(s, got[s], cache_dir); res.ok.append(s); res.full.append(s)
                meta[s] = {"years": years}
            else:
                res.failed[s] = "no data from yfinance"

    for i in range(0, len(full), chunk):
        b = full[i:i + chunk]
        log(f"[fetch] full {years}y download {i + 1}-{i + len(b)} / {len(full)}")
        _full(b)
        time.sleep(0.3)

    refetch: List[str] = []
    for start, group in incr.items():
        for i in range(0, len(group), chunk):
            b = group[i:i + chunk]
            log(f"[fetch] update {len(b)} tickers from {start}")
            try:
                got = _download(b, start=start)
            except Exception as e:  # pragma: no cover - network
                got = {}
                log(f"[fetch] batch error: {e}")
            for s in b:
                old, new = cached[s], got.get(s)
                if new is None or new.empty:
                    res.failed[s] = "no new data from yfinance (cache kept)"
                    continue
                ov = old.index.intersection(new.index)
                if len(ov):
                    a, b2 = old.loc[ov, "Close"].astype(float), new.loc[ov, "Close"].astype(float)
                    if ((a - b2).abs() / b2.abs()).max() > ADJ_TOL:
                        refetch.append(s)
                        continue
                merged = pd.concat([old[old.index < new.index[0]], new])
                save_cached(s, merged, cache_dir); res.ok.append(s); res.updated.append(s)
            time.sleep(0.3)
    if refetch:
        log(f"[fetch] adjustment changed for {len(refetch)} tickers -> full refetch")
        for i in range(0, len(refetch), chunk):
            _full(refetch[i:i + chunk])
    _save_meta(cache_dir, meta)
    return res
