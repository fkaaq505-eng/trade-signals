"""
Fetch full historical bars from the Alpaca CLI (read-only market data), following
pagination, into a clean OHLCV CSV that data_csv.py / the backtests can read.

READ-ONLY: shells out to `alpaca data bars` only. Never places an order, never
touches positions, never uses --live. Data fetch and nothing else.

    python alpaca_fetch.py SPY 5Min 2021-01-01 spy_5m.csv
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys

FEED = "iex"          # free-tier feed (SIP needs a paid subscription)
PAGE_LIMIT = 10_000   # Alpaca max bars per page


def fetch(symbol: str, timeframe: str, start: str) -> list[dict]:
    bars: list[dict] = []
    token, pages = None, 0
    while True:
        cmd = ["alpaca", "data", "bars", "--symbol", symbol, "--timeframe", timeframe,
               "--start", start, "--feed", FEED, "--limit", str(PAGE_LIMIT),
               "--adjustment", "split", "--sort", "asc"]
        if token:
            cmd += ["--page-token", token]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            raise SystemExit(f"non-JSON response: {r.stdout[:200]} | err {r.stderr[:200]}")
        if isinstance(data, dict) and data.get("error"):
            raise SystemExit(f"alpaca error: {data['error']}")
        page = data.get("bars") or []
        bars.extend(page)
        pages += 1
        token = data.get("next_page_token")
        print(f"  page {pages}: +{len(page)} (total {len(bars)})", file=sys.stderr)
        if not token:
            break
    return bars


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    timeframe = sys.argv[2] if len(sys.argv) > 2 else "5Min"
    start = sys.argv[3] if len(sys.argv) > 3 else "2021-01-01"
    out = sys.argv[4] if len(sys.argv) > 4 else f"{symbol}_{timeframe}.csv"

    bars = fetch(symbol, timeframe, start)
    if not bars:
        raise SystemExit("no bars returned (check auth / date range / feed).")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]])
    print(f"wrote {len(bars)} bars -> {out}  ({bars[0]['t']} .. {bars[-1]['t']})")


if __name__ == "__main__":
    main()
