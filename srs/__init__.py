"""srs: deterministic, tested building blocks for the stock-retest-scanner.

Pure functions (no network, no globals):
    to_weekly(daily_df, ...)        daily OHLCV -> W-FRI weekly OHLCV
    find_pivots(...) / trend(...)   primary trend from confirmed weekly swings
Network helpers:
    fetch(...)                      cached daily OHLCV from yfinance (auto-adjusted)
    info(ticker)                    inst own / short float / sector / market cap / next earnings
"""
from .weekly import to_weekly, last_complete_week_end
from .trend import trend, find_pivots, TREND_DEFAULTS
from .data import parse_tickers_file, load_cached, fetch_many, yf_symbol

__all__ = ["to_weekly", "last_complete_week_end", "trend", "find_pivots", "TREND_DEFAULTS",
           "parse_tickers_file", "load_cached", "fetch_many", "yf_symbol"]
__version__ = "0.1.0"
