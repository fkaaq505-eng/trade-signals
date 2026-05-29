"""
Load OHLCV from a local CSV so backtests can run on data Yahoo can't give us —
multi-year *intraday* history needed to honestly validate a funded strategy.

Legit sources (no scraping, no ToS issues):
  - TradingView: open the chart at your timeframe, then "Export chart data..."
    (available on paid plans) and point this loader at the file.
  - Alpaca (free API key, years of 1-min US-stock bars), Polygon.io free tier,
    Databento — download once to CSV, then load here.

Flexible columns (case-insensitive): a time/date column + open/high/low/close,
volume optional. Handles both unix-seconds and ISO timestamps.

    from data_csv import load_csv
    df = load_csv("SPY_5m.csv")
"""

from __future__ import annotations

import pandas as pd

_ALIASES = {
    "Open": ["open", "o"],
    "High": ["high", "h"],
    "Low": ["low", "l"],
    "Close": ["close", "c", "price"],
    "Volume": ["volume", "vol", "v"],
}
_TIME = ["time", "date", "datetime", "timestamp"]


def _find(cols_lower: dict[str, str], options: list[str]) -> str | None:
    for opt in options:
        if opt in cols_lower:
            return cols_lower[opt]
    return None


def load_csv(path: str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    cols_lower = {str(c).lower().strip(): c for c in raw.columns}

    tcol = _find(cols_lower, _TIME)
    if tcol is None:
        raise SystemExit(f"{path}: no time/date column (have {list(raw.columns)}).")

    out: dict[str, pd.Series] = {}
    for canon, aliases in _ALIASES.items():
        src = _find(cols_lower, aliases)
        if src is None and canon != "Volume":
            raise SystemExit(f"{path}: missing '{canon}' column (have {list(raw.columns)}).")
        if src is not None:
            out[canon] = pd.to_numeric(raw[src], errors="coerce")

    t = raw[tcol]
    unit = "s" if pd.api.types.is_numeric_dtype(t) else None
    # utc=True parses both tz-aware (mixed offsets) and naive uniformly; then drop
    # the tz so the whole pipeline stays on one consistent wall clock.
    idx = pd.to_datetime(t, unit=unit, errors="coerce", utc=True).dt.tz_localize(None)

    df = pd.DataFrame(out)
    df.index = pd.DatetimeIndex(idx)
    df = df[~df.index.isna()].dropna(subset=["Open", "High", "Low", "Close"]).sort_index()
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    if df.empty:
        raise SystemExit(f"{path}: no valid OHLC rows after parsing.")
    return df[["Open", "High", "Low", "Close", "Volume"]]
