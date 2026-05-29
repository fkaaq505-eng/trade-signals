"""
Funded-evaluation simulator. Runs the proven daily SPY meanrev trades through a
prop-firm evaluation with REAL rules — trailing drawdown and profit target — and,
crucially, tests the trailing-DD breach against each trade's intraday MAE (prop
drawdown is watched intraday, not close-to-close, which is what blows accounts).

    python fundeval.py                       # 50k acct, 4% trail, 6% target, 20% size
    python fundeval.py 50000 4 6 20          # account$, trailing%, target%, size%

Honest scope: this tells you whether the EXISTING daily strategy could pass a
SWING-allowed equities evaluation at a given size. It does NOT manufacture an
intraday futures edge — free data can't validate one. Daily-loss-limit rules are
not modelled (needs intraday marks); trailing DD is the usual account-killer and
is modelled via MAE.
"""

from __future__ import annotations

import sys

import pandas as pd

from data import fetch
from engine import backtest

ACCOUNT = float(sys.argv[1]) if len(sys.argv) > 1 else 50_000.0
TRAIL_PCT = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0     # trailing DD limit
TARGET_PCT = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0    # profit target
SIZE_PCT = float(sys.argv[4]) if len(sys.argv) > 4 else 20.0     # % of equity per trade
BAKED = dict(strategy="meanrev", rsi_buy=10, rsi_exit=75, down_days=2)


def main() -> None:
    df = fetch("SPY", "12y", "1d")
    trades, _ = backtest(df, sl_mult=0.0, max_hold_hours=240.0, skip_events=True, **BAKED)

    trail = ACCOUNT * TRAIL_PCT / 100.0
    target = ACCOUNT * (1.0 + TARGET_PCT / 100.0)
    equity = peak = ACCOUNT
    worst_trail = 0.0
    outcome, when = "INCOMPLETE (ran out of trades before hitting target)", None

    for i, t in enumerate(trades, 1):
        pos = equity * SIZE_PCT / 100.0
        # Intraday worst point during the trade (MAE) — the moment a trailing-DD
        # breach actually happens, before the trade recovers to its close.
        intraday_low_equity = equity + pos * (t.mae_pct / 100.0)
        worst_trail = max(worst_trail, peak - intraday_low_equity)
        if peak - intraday_low_equity > trail:
            outcome = (f"FAIL — trailing DD breached on trade #{i} ({t.entry_date[:10]}): "
                       f"intraday drawdown ${peak - intraday_low_equity:,.0f} > ${trail:,.0f} limit")
            when = i
            break
        # Realize the trade at its close.
        equity += pos * (t.pnl_pct / 100.0)
        peak = max(peak, equity)
        if equity >= target:
            outcome = (f"PASS — hit +{TARGET_PCT:.0f}% target on trade #{i} ({t.exit_date[:10]}), "
                       f"equity ${equity:,.0f}")
            when = i
            break

    print(f"\n=== FUNDED EVAL: SPY daily meanrev ===")
    print(f"account ${ACCOUNT:,.0f}  ·  trailing DD {TRAIL_PCT}% (${trail:,.0f})  ·  "
          f"target {TARGET_PCT}% (${target - ACCOUNT:,.0f})  ·  size {SIZE_PCT}%/trade")
    print(f"worst trailing drawdown reached:  ${worst_trail:,.0f}  "
          f"({100.0 * worst_trail / ACCOUNT:.1f}% of account, limit {TRAIL_PCT}%)")
    print(f"final equity:                     ${equity:,.0f}")
    print(f"\n  {outcome}")
    if when:
        held = pd.Timestamp(trades[when - 1].exit_date) - pd.Timestamp(trades[0].entry_date)
        print(f"  elapsed: ~{held.days} calendar days ({when} trades) — most evals have a "
              f"max-days clock too; this is slow.")
    print(f"\n  Note: trailing DD modelled via intraday MAE; daily-loss-limit not modelled. "
          f"Tune limits to YOUR firm: python fundeval.py <acct> <trail%> <target%> <size%>")


if __name__ == "__main__":
    main()
