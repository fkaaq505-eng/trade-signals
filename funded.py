"""
Funded-account (prop-firm) risk reality check for the SPY meanrev strategy.

Prop evaluations (FTMO, Topstep, Apex, MyFundedFutures, ...) fail you the instant
you breach a TRAILING or DAILY drawdown limit — and that is measured on live,
open-trade equity *intraday*, not close-to-close like the headline 82%/-6.8%
backtest. So the number that matters here is MAE: how deep underwater each trade
went before it eventually won or exited. A no-stop swing strategy can show a great
close-to-close record while still tagging a -X% intraday excursion that kills a
funded account.

This pulls the real MAE distribution and tells you, honestly, whether these
signals survive prop rules and at what position size.

    python funded.py                 # SPY, default 5% trailing / 4% daily limits
    python funded.py SPY 6 3         # symbol, trailing-DD %, daily-DD %

NOT trading advice. The honest answer is mostly "size down or don't".
"""

from __future__ import annotations

import sys

from data import fetch
from engine import backtest

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "SPY"
TRAILING_DD = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0   # % account
DAILY_DD = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0      # % account
BAKED = dict(strategy="meanrev", rsi_buy=10, rsi_exit=75, down_days=2)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main() -> None:
    df = fetch(SYMBOL, "12y", "1d")
    trades, _ = backtest(df, sl_mult=0.0, max_hold_hours=240.0, skip_events=True, **BAKED)
    if not trades:
        raise SystemExit("No trades to analyse.")

    maes = [t.mae_pct for t in trades]                       # all <= 0
    win_maes = [t.mae_pct for t in trades if t.pnl_pct > 0]  # winners' underwater depth
    holds_d = [t.hold_hours / 24.0 for t in trades]
    worst = min(maes)
    n = len(trades)

    def frac_worse(x: float) -> float:
        return round(100.0 * sum(1 for m in maes if m <= x) / n, 1)

    print(f"\n=== FUNDED-ACCOUNT REALITY CHECK: {SYMBOL} (meanrev, 12y, no stop) ===")
    print(f"trades {n}  ·  limits assumed: trailing {TRAILING_DD}% / daily {DAILY_DD}%\n")
    print(f"  worst trade MAE (deepest underwater)   {worst:.2f}%")
    print(f"  avg MAE (all trades)                   {mean(maes):.2f}%")
    print(f"  avg MAE of WINNING trades              {mean(win_maes):.2f}%  <- a stop would kill these")
    print(f"  trades that went worse than -1%        {frac_worse(-1.0)}%")
    print(f"  trades that went worse than -2%        {frac_worse(-2.0)}%")
    print(f"  trades that went worse than -3%        {frac_worse(-3.0)}%")
    print(f"  trades that went worse than -5%        {frac_worse(-5.0)}%")
    print(f"  longest hold                           {max(holds_d):.0f} calendar days "
          f"(overnight + weekend gap risk)")

    print("\n--- verdict ---")
    # 1) Intraday-only firms: a multi-day hold is disqualified outright.
    print(f"  Futures prop (Topstep/Apex/MFFU): these are usually FLAT-by-EOD or ban")
    print(f"  multi-day holds. A ~{max(holds_d):.0f}-day SPY swing does not fit -> use a different,")
    print(f"  intraday hard-stop strategy there. This tool is not built for it.")

    # 2) Swing-allowed equities firms: can it survive the DD limit, and at what size?
    full_breaches_daily = abs(worst) > DAILY_DD
    full_breaches_trail = abs(worst) > TRAILING_DD
    tightest = min(TRAILING_DD, DAILY_DD)
    safe_size = max(0.0, min(100.0, 100.0 * (tightest / abs(worst)) if worst else 100.0))
    print(f"\n  Swing-allowed equities account:")
    if full_breaches_daily or full_breaches_trail:
        print(f"  FULL SIZE FAILS — one bad trade's {worst:.1f}% excursion alone breaches the "
              f"{tightest:.0f}% limit.")
        print(f"  To keep the WORST historical trade inside the limit, cap position at "
              f"~{safe_size:.0f}% of the account;")
        print(f"  for a real safety buffer use about half that (~{safe_size/2:.0f}%). And know:")
        print(f"  past worst MAE is not a guaranteed ceiling — a future trade can be deeper.")
    else:
        print(f"  Survivable at full size on these limits (worst {worst:.1f}% < {tightest:.0f}%), "
              f"but keep a buffer; future trades can exceed the historical worst.")
    print(f"\n  Honest bottom line: this strategy's edge is sitting in cash and NOT using a")
    print(f"  stop — the opposite of what prop rules reward. Best fit is your own paper/cash")
    print(f"  account. For funded, size tiny + add a catastrophe stop, or pick a different tool.")


if __name__ == "__main__":
    main()
