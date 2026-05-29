"""
Trading-session filter. Index moves are cleanest during specific hours; thin
overnight liquidity = whipsaw + slippage. We only allow ENTRIES during a chosen
session window. All times are US Eastern (ET), since the S&P/Nasdaq cash market
sets the tone for both ETFs and index futures.

Windows are minutes-of-day in ET, [start, end).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")


def _m(h: int, m: int = 0) -> int:
    return h * 60 + m


SESSIONS: dict[str, tuple[int, int] | None] = {
    "all": None,                       # no filter
    "us": (_m(9, 30), _m(16)),          # NYSE cash 9:30-16:00 ET
    "us_morning": (_m(9, 30), _m(12)),  # cleanest trend (DEFAULT)
    "us_power": (_m(9, 30), _m(11)),    # first 90 min, highest volatility
    "london_ny": (_m(8), _m(11)),       # EU/US overlap (best for futures)
}


def is_intraday(index: pd.DatetimeIndex) -> bool:
    """Daily bars all sit at midnight; intraday bars don't."""
    return not bool((index.normalize() == index).all())


def to_et(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if index.tz is None:
        index = index.tz_localize("UTC")
    return index.tz_convert(ET)


def in_session_mask(index: pd.DatetimeIndex, session: str) -> pd.Series:
    """True where a bar's timestamp falls inside the session window.

    Daily data (or session='all') is never filtered — returns all True.
    """
    window = SESSIONS.get(session)
    if window is None or not is_intraday(index):
        return pd.Series(True, index=index)
    et = to_et(index)
    minutes = et.hour * 60 + et.minute
    start, end = window
    return pd.Series((minutes >= start) & (minutes < end), index=index)
