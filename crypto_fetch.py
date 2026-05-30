"""
Fetch historical OHLCV from public crypto APIs (no key required) and write a
clean CSV compatible with data_csv.load_csv().

Tries exchanges in this order, falling through on errors or geo-blocks:
  1. Binance  (GET /api/v3/klines, 1000 bars/page, paginate via startTime)
  2. Coinbase (GET /products/{pair}/candles, 300 bars/page, paginate via start/end)
  3. Kraken   (GET /0/public/OHLC, ~720 recent bars only — weak history, last resort)

CSV output: time,open,high,low,close,volume  (ISO timestamps, UTC)

Usage:
    python crypto_fetch.py BTCUSDT 5m 2023-01-01 btc_5m.csv
    python crypto_fetch.py ETHUSD  5m 2023-01-01 eth_5m.csv
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timezone

import requests

# ── constants ────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 30          # seconds per HTTP call
BINANCE_PAGE = 1_000          # bars per Binance request (API max)
COINBASE_PAGE = 300           # bars per Coinbase request (API max)
RETRY_SLEEP = 2.0             # seconds between retries on rate-limit / 5xx
MAX_RETRIES = 3

BINANCE_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}
COINBASE_GRANULARITIES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}
KRAKEN_INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}

# symbol mapping helpers
BINANCE_TO_COINBASE = {
    "BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD",
    "SOLUSDT": "SOL-USD", "AVAXUSDT": "AVAX-USD",
    "BNBUSDT": "BNB-USD",
}
BINANCE_TO_KRAKEN = {
    "BTCUSDT": "XBTUSD", "ETHUSDT": "ETHUSD",
    "SOLUSDT": "SOLUSD", "AVAXUSDT": "AVAXUSD",
}


# ── low-level HTTP helpers ────────────────────────────────────────────────────

def _get(url: str, params: dict) -> dict | list:
    """GET with retries on 429 / 5xx; raises on other errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            print(f"  network error ({exc}), retry {attempt}/{MAX_RETRIES}...", file=sys.stderr)
            time.sleep(RETRY_SLEEP)
            continue
        if r.status_code in (429, 418):
            wait = float(r.headers.get("Retry-After", RETRY_SLEEP * attempt))
            print(f"  rate-limit ({r.status_code}), sleeping {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            if attempt == MAX_RETRIES:
                r.raise_for_status()
            print(f"  server error {r.status_code}, retry {attempt}/{MAX_RETRIES}...", file=sys.stderr)
            time.sleep(RETRY_SLEEP * attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("max retries exceeded")


# ── Binance fetcher ───────────────────────────────────────────────────────────

def _binance_fetch(symbol: str, interval: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Paginate Binance klines from start_dt to end_dt."""
    if interval not in BINANCE_INTERVALS:
        raise ValueError(f"Binance does not support interval '{interval}'")

    url = "https://api.binance.com/api/v3/klines"
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    bars: list[dict] = []
    page = 0

    while start_ms < end_ms:
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": BINANCE_PAGE,
        }
        raw = _get(url, params)
        if not isinstance(raw, list):
            raise ValueError(f"Binance: unexpected response type {type(raw)}: {str(raw)[:200]}")
        if not raw:
            break
        for k in raw:
            # k[0]=open_time_ms, k[1]=open, k[2]=high, k[3]=low, k[4]=close, k[5]=volume
            bars.append({
                "t": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
                "v": float(k[5]),
            })
        page += 1
        last_open_ms = raw[-1][0]
        # Advance past the last bar's open time (kline interval in ms)
        interval_ms = int((last_open_ms - (raw[0][0])) / max(len(raw) - 1, 1)) if len(raw) > 1 else 300_000
        start_ms = last_open_ms + interval_ms
        print(f"  binance page {page}: +{len(raw)} (total {len(bars)}, up to {bars[-1]['t']})", file=sys.stderr)
        if len(raw) < BINANCE_PAGE:
            break

    return bars


# ── Coinbase fetcher ──────────────────────────────────────────────────────────

def _coinbase_fetch(symbol: str, interval: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Paginate Coinbase Exchange candles from start_dt to end_dt."""
    gran = COINBASE_GRANULARITIES.get(interval)
    if gran is None:
        raise ValueError(f"Coinbase does not support interval '{interval}'")

    # Translate symbol: accept either "BTC-USD" or "BTCUSDT"
    pair = BINANCE_TO_COINBASE.get(symbol.upper(), symbol.upper())
    url = f"https://api.exchange.coinbase.com/products/{pair}/candles"
    page_seconds = COINBASE_PAGE * gran
    bars: list[dict] = []
    cursor = start_dt
    page = 0

    while cursor < end_dt:
        window_end = min(end_dt, datetime.fromtimestamp(
            cursor.timestamp() + page_seconds, tz=timezone.utc))
        params = {
            "granularity": gran,
            "start": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        raw = _get(url, params)
        if not isinstance(raw, list):
            raise ValueError(f"Coinbase: unexpected response type: {str(raw)[:200]}")
        if not raw:
            cursor = window_end
            continue
        # Coinbase returns [time_unix, low, high, open, close, volume] newest-first
        for k in raw:
            ts = datetime.fromtimestamp(k[0], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            bars.append({"t": ts, "o": float(k[3]), "h": float(k[2]),
                         "l": float(k[1]), "c": float(k[4]), "v": float(k[5])})
        page += 1
        print(f"  coinbase page {page}: +{len(raw)} (total {len(bars)}, up to {window_end.strftime('%Y-%m-%d')})",
              file=sys.stderr)
        cursor = window_end
        time.sleep(0.12)   # stay well under Coinbase's 10 req/s public limit

    return bars


# ── Kraken fetcher ────────────────────────────────────────────────────────────

def _kraken_fetch(symbol: str, interval: str, start_dt: datetime) -> list[dict]:
    """Fetch Kraken OHLC (~720 most-recent bars, not paginated)."""
    kraken_iv = KRAKEN_INTERVALS.get(interval)
    if kraken_iv is None:
        raise ValueError(f"Kraken does not support interval '{interval}'")

    pair = BINANCE_TO_KRAKEN.get(symbol.upper(), symbol.upper())
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": pair, "interval": kraken_iv, "since": int(start_dt.timestamp())}
    raw = _get(url, params)
    if raw.get("error"):
        raise ValueError(f"Kraken API error: {raw['error']}")
    data_dict = raw.get("result", {})
    # result has one key (the canonical pair name) and a "last" key
    rows = None
    for k, v in data_dict.items():
        if k != "last" and isinstance(v, list):
            rows = v
            break
    if not rows:
        raise ValueError("Kraken: no OHLC data in response")

    bars = []
    for k in rows:
        # [time, open, high, low, close, vwap, volume, count]
        ts = datetime.fromtimestamp(int(k[0]), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bars.append({"t": ts, "o": float(k[1]), "h": float(k[2]),
                     "l": float(k[3]), "c": float(k[4]), "v": float(k[6])})
    print(f"  kraken: {len(bars)} bars", file=sys.stderr)
    return bars


# ── dedup + validate ──────────────────────────────────────────────────────────

def _clean(bars: list[dict]) -> list[dict]:
    """Sort by time, deduplicate, drop NaN-like rows, validate OHLC sanity."""
    seen: set[str] = set()
    cleaned = []
    for b in bars:
        if b["t"] in seen:
            continue
        if any(b[k] != b[k] for k in ("o", "h", "l", "c")):   # NaN check
            continue
        if b["h"] < b["l"] or b["h"] < b["o"] or b["h"] < b["c"]:
            continue
        if b["l"] > b["o"] or b["l"] > b["c"]:
            continue
        if b["c"] <= 0 or b["o"] <= 0:
            continue
        seen.add(b["t"])
        cleaned.append(b)
    cleaned.sort(key=lambda x: x["t"])
    return cleaned


# ── public entry point ────────────────────────────────────────────────────────

def fetch(symbol: str, interval: str, start: str, end: str | None = None) -> list[dict]:
    """
    Fetch OHLCV bars from the best available public exchange.
    Returns list of {t, o, h, l, c, v} sorted ascending by time.
    """
    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = (datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
              if end else datetime.now(tz=timezone.utc))

    # Try Binance first
    try:
        print(f"[crypto_fetch] trying Binance ({symbol}, {interval})...", file=sys.stderr)
        bars = _binance_fetch(symbol, interval, start_dt, end_dt)
        if bars:
            return _clean(bars)
        print("  Binance returned 0 bars, falling through.", file=sys.stderr)
    except Exception as exc:
        print(f"  Binance failed: {exc}. Trying Coinbase...", file=sys.stderr)

    # Try Coinbase
    try:
        print(f"[crypto_fetch] trying Coinbase ({symbol}, {interval})...", file=sys.stderr)
        bars = _coinbase_fetch(symbol, interval, start_dt, end_dt)
        if bars:
            return _clean(bars)
        print("  Coinbase returned 0 bars, falling through.", file=sys.stderr)
    except Exception as exc:
        print(f"  Coinbase failed: {exc}. Trying Kraken...", file=sys.stderr)

    # Last resort: Kraken (~720 bars only)
    print(f"[crypto_fetch] trying Kraken ({symbol}, {interval})...", file=sys.stderr)
    bars = _kraken_fetch(symbol, interval, start_dt)
    return _clean(bars)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 5:
        print("Usage: python crypto_fetch.py SYMBOL INTERVAL START_DATE OUT.csv [END_DATE]",
              file=sys.stderr)
        print("  e.g.: python crypto_fetch.py BTCUSDT 5m 2023-01-01 btc_5m.csv", file=sys.stderr)
        sys.exit(1)

    symbol = sys.argv[1]
    interval = sys.argv[2]
    start = sys.argv[3]
    out = sys.argv[4]
    end = sys.argv[5] if len(sys.argv) > 5 else None

    bars = fetch(symbol, interval, start, end)
    if not bars:
        raise SystemExit("No bars returned from any exchange. Check symbol/interval/dates.")

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]])

    print(f"wrote {len(bars)} bars -> {out}  ({bars[0]['t']} .. {bars[-1]['t']})")


if __name__ == "__main__":
    main()
