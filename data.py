"""Shared data fetch (Yahoo Finance via yfinance). Used by cli.py and notify.py."""

from __future__ import annotations

import yfinance as yf


def fetch(symbol: str, period: str, interval: str):
    df = yf.download(symbol, period=period, interval=interval,
                     auto_adjust=True, progress=False)
    if df.empty:
        raise SystemExit(
            f"No data for {symbol!r} (period={period}, interval={interval}). "
            f"Note: Yahoo caps 1h history at ~730d, 15m/30m at ~60d."
        )
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
