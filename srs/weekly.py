"""Daily -> weekly candles (pure, no I/O).

Matches stock_screen.to_weekly() exactly when called with defaults (W-FRI resample, open=first,
high=max, low=min, close=last, volume=sum, empty weeks dropped). Extra options:
  asof            cut the daily data at this date (inclusive) before resampling
  drop_incomplete drop the last week if it is still in progress at the reference date
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Union

import pandas as pd

DateLike = Union[str, date, pd.Timestamp, None]
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _ts(d: DateLike) -> Optional[pd.Timestamp]:
    return None if d is None else pd.Timestamp(d).normalize()


def normalize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """DatetimeIndex (tz-naive, sorted, unique) + the 5 OHLCV columns (title case)."""
    d = daily.copy()
    d.columns = [str(c).strip().title() for c in d.columns]
    if "Date" in d.columns:
        d = d.set_index("Date")
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    d.index.name = "Date"
    d = d[~d.index.duplicated(keep="last")].sort_index()
    missing = [c for c in OHLCV if c not in d.columns]
    if missing:
        raise ValueError(f"daily frame is missing columns {missing}")
    return d[OHLCV]


def week_end(d: DateLike) -> pd.Timestamp:
    """The Friday that closes the W-FRI week containing `d`."""
    t = _ts(d)
    return t + timedelta(days=(4 - t.weekday()) % 7)


def last_complete_week_end(ref: DateLike) -> pd.Timestamp:
    """Most recent Friday <= ref (the last W-FRI week that is complete on date `ref`)."""
    t = _ts(ref)
    return t - timedelta(days=(t.weekday() - 4) % 7)


def to_weekly(daily: pd.DataFrame, asof: DateLike = None, drop_incomplete: bool = False) -> pd.DataFrame:
    """W-FRI weekly OHLCV, index = the week's Friday.

    asof:            only daily bars with date <= asof are used.
    drop_incomplete: drop the last week when the reference date (asof, else the last daily bar)
                     is before that week's Friday. A holiday-shortened week whose last session is
                     Thursday therefore counts as complete only once the reference date reaches
                     Friday (pass asof to make that explicit).
    """
    d = normalize_daily(daily)
    if asof is not None:
        d = d[d.index <= _ts(asof)]
    if d.empty:
        return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([], name="Date"))
    w = d.resample("W-FRI").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()
    if drop_incomplete and len(w):
        ref = _ts(asof) if asof is not None else d.index[-1].normalize()
        w = w[w.index <= ref]
    return w
