"""
Head-to-head strategy comparison on one symbol. Rule: only adopt a new strategy
if it beats the current default on win rate AND net AND drawdown together — no
cherry-picking one metric.

    python compare.py        # SPY
    python compare.py QQQ
"""

from __future__ import annotations

import sys

from data import fetch
from engine import backtest, stats

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "SPY"

CANDIDATES = [
    ("meanrev RSI2 (current)", dict(strategy="meanrev", rsi_buy=10, rsi_exit=75)),
    ("meanrev + 2 down days", dict(strategy="meanrev", rsi_buy=10, rsi_exit=75, down_days=2)),
    ("meanrev + 3 down days", dict(strategy="meanrev", rsi_buy=10, rsi_exit=75, down_days=3)),
    ("meanrev RSI2<5 (deeper)", dict(strategy="meanrev", rsi_buy=5, rsi_exit=75)),
    ("bollinger reversion", dict(strategy="bb")),
]


def main() -> None:
    df = fetch(SYMBOL, "12y", "1d")
    buy_hold = df["Close"] / df["Close"].iloc[0]

    rows = []
    for label, kw in CANDIDATES:
        trades, eq = backtest(df, sl_mult=0.0, max_hold_hours=240.0,
                              skip_events=True, **kw)
        rows.append((label, stats(trades, eq, buy_hold)))

    print(f"\n=== COMPARE {SYMBOL} (12y daily, event-filter on) — "
          f"buy_hold {rows[0][1].get('buy_hold_return_%')}% ===")
    print(f"{'strategy':<26}{'trades':>7}{'win%':>7}{'PF':>6}{'net%':>8}{'maxDD%':>8}")
    print("-" * 62)
    for label, s in rows:
        if s.get("trades", 0) == 0:
            print(f"{label:<26}{'(no trades)':>7}")
            continue
        print(f"{label:<26}{s['trades']:>7}{s['win_rate_%']:>7}"
              f"{s['profit_factor']:>6}{s['net_return_%(after fees)']:>8}{s['max_drawdown_%']:>8}")

    live = [r for r in rows if r[1].get("trades", 0) >= 25]
    if live:
        best = max(live, key=lambda r: (r[1]["win_rate_%"], r[1]["net_return_%(after fees)"]))
        print(f"\nBEST (win rate, >=25 trades): {best[0]} -> {best[1]['win_rate_%']}% win, "
              f"net {best[1]['net_return_%(after fees)']}%, DD {best[1]['max_drawdown_%']}%")


if __name__ == "__main__":
    main()
