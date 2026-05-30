"""
Honest intraday "accuracy vs profit" bake-off for funded-style strategies. Shows
WIN RATE next to EXPECTANCY (avg % per trade) and NET so a high win rate can't
hide a money-loser — the fake-accuracy trap this project bans.

All funded-compatible: hard stop + flat-by-close (eod_flat), intraday bars.

    python intraday_compare.py                 # SPY 15m Yahoo (~60d, illustrative)
    python intraday_compare.py SPY_15m.csv     # your deep intraday CSV (preferred)

*** ~60d of free data = NOT validation. Mechanics/ranking only. ***
"""

from __future__ import annotations

import sys

from data import fetch
from data_csv import load_csv
from engine import backtest, stats

# (label, strategy, stop xATR) — all high-win-rate mean-reversion families.
CANDIDATES = [
    ("RSI2 intraday", "meanrev", 1.0),
    ("RSI2 tighter stop", "meanrev", 0.5),
    ("VWAP reversion", "vwap", 1.0),
    ("Bollinger intraday", "bb", 1.0),
]


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else None
    df = load_csv(src) if src and src.lower().endswith(".csv") else fetch("SPY", "60d", "15m")
    buy_hold = df["Close"] / df["Close"].iloc[0]
    span = (df.index[-1] - df.index[0]).days

    print(f"\n=== INTRADAY ACCURACY-vs-PROFIT ({src or 'SPY 15m Yahoo'}, ~{span}d, "
          f"hard stop + EOD-flat) ===")
    print(f"*** ~60d free data = ranking/mechanics only, NOT a validated edge ***")
    print(f"buy_hold over window: {100*(buy_hold.iloc[-1]-1):+.1f}%\n")
    print(f"{'strategy':<20}{'trades':>7}{'win%':>7}{'exp/trade%':>11}{'net%':>8}"
          f"{'maxDD%':>8}{'worstMAE%':>10}")
    print("-" * 71)

    rows = []
    for label, strat, sl in CANDIDATES:
        trades, eq = backtest(df, strategy=strat, sl_mult=sl, max_hold_hours=24.0,
                              skip_events=False, eod_flat=True)
        s = stats(trades, eq, buy_hold)
        if s.get("trades", 0) == 0:
            print(f"{label:<20}{'(no trades)':>7}")
            continue
        worst_mae = min((t.mae_pct for t in trades), default=0.0)
        rows.append((label, s))
        print(f"{label:<20}{s['trades']:>7}{s['win_rate_%']:>7}{s['avg_trade_%']:>11}"
              f"{s['net_return_%(after fees)']:>8}{s['max_drawdown_%']:>8}{worst_mae:>10.2f}")

    print("\n--- honest read ---")
    if not rows:
        print("  no trades to judge.")
        return
    best_win = max(rows, key=lambda r: r[1]["win_rate_%"])
    best_net = max(rows, key=lambda r: r[1]["net_return_%(after fees)"])
    print(f"  highest WIN RATE:  {best_win[0]} ({best_win[1]['win_rate_%']}%) "
          f"-> net {best_win[1]['net_return_%(after fees)']}%")
    print(f"  highest NET:       {best_net[0]} ({best_net[1]['net_return_%(after fees)']}%) "
          f"-> win {best_net[1]['win_rate_%']}%")
    if best_net[1]["net_return_%(after fees)"] <= buy_hold.iloc[-1] * 100 - 100:
        print("  NOTE: even the best NET trails buy-hold. High accuracy here is NOT "
              "more money —\n  it is the win-rate illusion. None of these is a proven "
              "funded edge on this data.")


if __name__ == "__main__":
    main()
