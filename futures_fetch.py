"""
Pull futures / index-CFD data from two free sources and save as standard CSVs.

ROUTE 1 — Yahoo Finance continuous futures (NQ=F, ES=F):
  - 1h / 730d  (~2.4 years, real Nasdaq/S&P futures, includes Globex overnight)
  - 5m / 60d   (~2 months fine-grain sanity check only)

ROUTE 2 — Dukascopy free chart API (index CFDs that track NQ/ES):
  - E_NQ-100   = Nasdaq-100 CFD  ≈ NQ futures
  - E_SandP-500 = S&P-500 CFD   ≈ ES futures
  - 5m, 2021-01-01 → today (multi-year OOS test)
  - 1h, same span (model development)

Honest caveat on the Dukascopy CFDs:
  These are index CFDs quoted as mid-prices by Dukascopy Bank. They closely track
  the underlying index (and thus the futures) but are NOT the futures contract
  itself. There is no roll cost or basis in the data. Prices are in index points.
  State clearly in any report: "Dukascopy E_NQ-100 / E_SandP-500 index CFD".

Output format: time,open,high,low,close,volume  (UTC naive, matching data_csv.py)

Usage:
    python futures_fetch.py            # fetch everything
    python futures_fetch.py yahoo      # Yahoo only
    python futures_fetch.py duka       # Dukascopy only
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

import dukascopy_python as dk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
YAHOO_SYMBOLS = [("NQ=F", "1h", "730d"), ("ES=F", "1h", "730d"),
                 ("NQ=F", "5m",  "60d"),  ("ES=F", "5m",  "60d")]

DUKA_INSTRUMENTS = [
    ("E_NQ-100",     "nq_cfd"),
    ("E_SandP-500",  "es_cfd"),
]
DUKA_INTERVALS = [
    (dk.INTERVAL_MIN_5,  "5m"),
    (dk.INTERVAL_HOUR_1, "1h"),
]
DUKA_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
DUKA_BATCH_DAYS = 90   # fetch in 90-day windows to stay inside the 30k limit
DUKA_LIMIT      = 30_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _std_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize to time,open,high,low,close,volume with UTC-naive index."""
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None) if df.index.tz is None \
        else pd.DatetimeIndex(df.index).tz_convert(None)
    df.index.name = "time"
    if "Volume" in df.columns:
        df = df.rename(columns={"Open": "open", "High": "high",
                                 "Low": "low", "Close": "close", "Volume": "volume"})
    elif "volume" not in df.columns:
        df = df.assign(volume=0.0)
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


def _validate(df: pd.DataFrame, label: str) -> None:
    """Raise SystemExit if the dataframe fails basic sanity checks."""
    if df.empty:
        raise SystemExit(f"[FAIL] {label}: empty after cleaning.")
    if df.index.isna().any():
        raise SystemExit(f"[FAIL] {label}: NaT timestamps after parsing.")
    if not df.index.is_monotonic_increasing:
        raise SystemExit(f"[FAIL] {label}: index not sorted after dedup.")
    nan_rows = df[["open", "high", "low", "close"]].isna().any(axis=1).sum()
    if nan_rows > 0:
        raise SystemExit(f"[FAIL] {label}: {nan_rows} rows with NaN OHLC remaining.")


def _save(df: pd.DataFrame, path: str, label: str) -> None:
    _validate(df, label)
    df.to_csv(path)
    span_days = (df.index[-1] - df.index[0]).days
    print(f"[OK] {label}: {len(df):,} bars | {df.index[0].date()} → {df.index[-1].date()} "
          f"({span_days}d) → {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Route 1: Yahoo
# ---------------------------------------------------------------------------
def fetch_yahoo_all() -> None:
    for symbol, interval, period in YAHOO_SYMBOLS:
        label = f"Yahoo {symbol} {interval}/{period}"
        print(f"[...] Fetching {label} ...", file=sys.stderr)
        try:
            raw = yf.download(symbol, period=period, interval=interval,
                              auto_adjust=True, progress=False)
        except Exception as exc:
            print(f"[WARN] {label}: download error: {exc}", file=sys.stderr)
            continue
        if raw.empty:
            print(f"[WARN] {label}: no data returned.", file=sys.stderr)
            continue
        if hasattr(raw.columns, "nlevels") and raw.columns.nlevels > 1:
            raw.columns = raw.columns.get_level_values(0)
        df = _std_cols(raw)
        slug = symbol.replace("=", "").lower()
        path = f"{slug}_{interval}_{period}.csv"
        _save(df, path, label)


# ---------------------------------------------------------------------------
# Route 2: Dukascopy (batched to stay within 30k row limit)
# ---------------------------------------------------------------------------
def _fetch_duka_batched(instrument: str, interval: str,
                        start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch instrument in DUKA_BATCH_DAYS-day chunks and concatenate."""
    from datetime import timedelta

    chunks: list[pd.DataFrame] = []
    cursor = start
    while cursor < end:
        batch_end = min(cursor + timedelta(days=DUKA_BATCH_DAYS), end)
        try:
            chunk = dk.fetch(instrument, interval, dk.OFFER_SIDE_BID,
                             cursor, batch_end, limit=DUKA_LIMIT)
        except Exception as exc:
            print(f"[WARN] {instrument} {interval} batch {cursor.date()} error: {exc}",
                  file=sys.stderr)
            cursor = batch_end
            continue
        if not chunk.empty:
            chunks.append(chunk)
        cursor = batch_end

    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks)


def fetch_duka_all() -> None:
    end = datetime.now(tz=timezone.utc)

    for instrument, slug in DUKA_INSTRUMENTS:
        for interval, tf_label in DUKA_INTERVALS:
            label = f"Dukascopy {instrument} {tf_label}"
            print(f"[...] Fetching {label} (2021-now, batched) ...", file=sys.stderr)
            raw = _fetch_duka_batched(instrument, interval, DUKA_START, end)
            if raw.empty:
                print(f"[WARN] {label}: no data.", file=sys.stderr)
                continue
            # Rename columns to match standard format
            raw = raw.rename(columns={"open": "open", "high": "high",
                                       "low": "low", "close": "close",
                                       "volume": "volume"})
            raw.index = raw.index.tz_convert(None)
            raw.index.name = "time"
            raw = raw.dropna(subset=["open", "high", "low", "close"])
            raw = raw[~raw.index.duplicated(keep="first")].sort_index()
            if "volume" not in raw.columns:
                raw = raw.assign(volume=0.0)
            raw = raw[["open", "high", "low", "close", "volume"]]
            path = f"{slug}_{tf_label}_duka.csv"
            _save(raw, path, label)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    if mode in ("yahoo", "all"):
        fetch_yahoo_all()
    if mode in ("duka", "all"):
        fetch_duka_all()
    print("[done] futures_fetch.py complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
