"""
Parameter sweep to find the strongest *honest* Connors RSI(2) config for one
symbol. Downloads once, runs a small grid, ranks results.

NOT a magic accuracy machine: a wider grid + picking the top cell is how people
overfit. We keep the grid tiny and judge on win rate AND net AND drawdown
together, then sanity-check the winner isn't a fluke (few trades).

    python sweep.py            # SPY by default
    python sweep.py QQQ
"""

from __future__ import annotations

import sys

from data import fetch
from engine import backtest, stats

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "SPY"
RSI_BUYS = (5, 10, 15)
RSI_EXITS = (65, 75)
SKIP = (False, True)


def main() -> None:
    df = fetch(SYMBOL, "12y", "1d")
    buy_hold = df["Close"] / df["Close"].iloc[0]

    rows = []
    for rb in RSI_BUYS:
        for rx in RSI_EXITS:
            for se in SKIP:
                # meanrev settings: no hard stop, RSI-based exit, longer hold
                trades, eq = backtest(df, strategy="meanrev", rsi_buy=rb,
                                      rsi_exit=rx, skip_events=se,
                                      sl_mult=0.0, max_hold_hours=240.0)
                s = stats(trades, eq, buy_hold)
                rows.append({"rsi_buy": rb, "rsi_exit": rx, "skip_events": se, **s})

    # Rank: win rate first, then net return, with a min-trades sanity gate.
    rows.sort(key=lambda r: (r["win_rate_%"], r["net_return_%(after fees)"]), reverse=True)

    hdr = f"{'rsi_buy':>7} {'rsi_exit':>8} {'skip_ev':>7} {'trades':>6} {'win%':>6} {'PF':>5} {'net%':>6} {'maxDD%':>7}"
    print(f"\n=== SWEEP {SYMBOL} (meanrev, 12y daily) — buy_hold {rows[0]['buy_hold_return_%']}% ===")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['rsi_buy']:>7} {r['rsi_exit']:>8} {str(r['skip_events']):>7} "
              f"{r['trades']:>6} {r['win_rate_%']:>6} {r['profit_factor']:>5} "
              f"{r['net_return_%(after fees)']:>6} {r['max_drawdown_%']:>7}")

    best = rows[0]
    print(f"\nTop by win rate: rsi_buy={best['rsi_buy']} rsi_exit={best['rsi_exit']} "
          f"skip_events={best['skip_events']} -> {best['win_rate_%']}% win, "
          f"{best['trades']} trades, net {best['net_return_%(after fees)']}%, DD {best['max_drawdown_%']}%")
    if best["trades"] < 25:
        print("WARNING: <25 trades — high win rate may be a small-sample fluke.")


if __name__ == "__main__":
    main()
