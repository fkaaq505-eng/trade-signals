"""
VIX-regime experiment for the SPY mean-reversion strategy. Does gating entries by
the VIX level beat the current (no-gate) champion on win AND net AND drawdown?

Mean reversion has two opposing intuitions about volatility:
  - high VIX = maximum fear = the deepest, springiest dips (Connors' edge), OR
  - high VIX = a regime break where dips keep falling and don't revert.
The 200-day SMA filter already blocks most crash-buying (price is usually below
it in a real bear), so a VIX gate only bites on sharp vol spikes *inside* an
uptrend. This script lets the data settle the argument honestly.

Same discipline as compare.py: only adopt a gate if it beats the current default
on win rate AND net AND drawdown together. buy_hold shown for context.

    python vixtest.py            # SPY
    python vixtest.py QQQ

NEVER trades. Simulation only.
"""

from __future__ import annotations

import sys
from math import inf

from data import fetch
from engine import backtest, stats

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "SPY"
BAKED = dict(strategy="meanrev", rsi_buy=10, rsi_exit=75, down_days=2)

# (label, vix_min, vix_max). First row is the current champion (no gate).
VARIANTS = [
    ("current (no VIX gate)", 0.0, inf),
    ("VIX < 25 (skip stress)", 0.0, 25.0),
    ("VIX < 30 (skip panic)", 0.0, 30.0),
    ("VIX > 15 (need vol)", 15.0, inf),
    ("VIX 15-30 (band)", 15.0, 30.0),
    ("VIX 13-35 (wide band)", 13.0, 35.0),
]


def main() -> None:
    spy = fetch(SYMBOL, "12y", "1d")
    vix = fetch("^VIX", "12y", "1d")["Close"]
    buy_hold = spy["Close"] / spy["Close"].iloc[0]
    vix_now = float(vix.reindex(spy.index).ffill().iloc[-1])

    rows = []
    for label, lo, hi in VARIANTS:
        trades, eq = backtest(spy, sl_mult=0.0, max_hold_hours=240.0,
                              skip_events=True, vix=vix, vix_min=lo, vix_max=hi,
                              **BAKED)
        rows.append((label, stats(trades, eq, buy_hold)))

    cur = rows[0][1]
    print(f"\n=== VIX TEST {SYMBOL} (12y daily, meanrev baked) — "
          f"buy_hold {cur['buy_hold_return_%']}%  ·  VIX now ~{vix_now:.0f} ===")
    print(f"{'variant':<24}{'trades':>7}{'win%':>7}{'PF':>6}{'net%':>8}{'maxDD%':>8}")
    print("-" * 60)
    for label, s in rows:
        if s.get("trades", 0) == 0:
            print(f"{label:<24}{'(no trades)':>7}")
            continue
        print(f"{label:<24}{s['trades']:>7}{s['win_rate_%']:>7}{s['profit_factor']:>6}"
              f"{s['net_return_%(after fees)']:>8}{s['max_drawdown_%']:>8}")

    # Adoption gate: beat current on win AND net AND drawdown (all three).
    def beats(s) -> bool:
        return (s["win_rate_%"] > cur["win_rate_%"]
                and s["net_return_%(after fees)"] > cur["net_return_%(after fees)"]
                and s["max_drawdown_%"] > cur["max_drawdown_%"])   # less negative

    winners = [(label, s) for label, s in rows[1:]
               if s.get("trades", 0) >= 25 and beats(s)]
    print()
    if winners:
        label, s = max(winners, key=lambda r: (r[1]["win_rate_%"],
                                                r[1]["net_return_%(after fees)"]))
        print(f"ADOPT CANDIDATE: {label} beats current on win+net+DD "
              f"({s['win_rate_%']}% / {s['net_return_%(after fees)']}% / {s['max_drawdown_%']}%).")
    else:
        print("VERDICT: no VIX gate beats current on win AND net AND drawdown. "
              "Keep the no-gate champion. (The 200SMA filter already does this job.)")


if __name__ == "__main__":
    main()
