"""
Screen liquid equity index/sector ETFs for the SAME validated Connors-RSI2
mean-reversion edge as SPY, to build a higher-frequency basket WITHOUT leaving the
market where the edge is real. ETFs (not single stocks) = no earnings gaps, can't
go to zero. Keep only names that clear the gate; reject the rest.

    python screen.py
"""

from __future__ import annotations

from data import fetch
from engine import backtest, stats

CANDIDATES = [
    "SPY", "QQQ", "DIA", "IWM", "MDY", "VTI",                      # broad
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLB",  # sectors
    "SMH", "IYR", "XBI", "KRE", "ITB",                             # industries
    "EFA", "EEM", "EWJ", "FXI",                                    # international
]
# Gate: a real, tradeable edge needs a high win rate, positive net, and enough
# trades to trust it. Tuned to match SPY's profile, not cherry-picked.
MIN_WIN, MIN_TRADES = 72.0, 30


def main() -> None:
    rows = []
    for sym in CANDIDATES:
        try:
            df = fetch(sym, "12y", "1d")
        except SystemExit:
            print(f"{sym:<5} (no data)")
            continue
        trades, eq = backtest(df, strategy="meanrev", rsi_buy=10, rsi_exit=75,
                              down_days=2, skip_events=True, sl_mult=0.0,
                              max_hold_hours=240.0)
        s = stats(trades, eq, df["Close"] / df["Close"].iloc[0])
        if s.get("trades", 0) == 0:
            print(f"{sym:<5} (no trades)")
            continue
        rows.append((sym, s))

    rows.sort(key=lambda r: r[1]["win_rate_%"], reverse=True)
    print(f"\n=== ETF meanrev screen (12y daily, baked config) ===")
    print(f"{'sym':<6}{'trades':>7}{'win%':>7}{'PF':>6}{'net%':>8}{'maxDD%':>8}"
          f"{'buyhold%':>10}  edge?")
    print("-" * 60)
    keep = []
    for sym, s in rows:
        ok = (s["win_rate_%"] >= MIN_WIN and s["trades"] >= MIN_TRADES
              and s["net_return_%(after fees)"] > 0)
        if ok:
            keep.append(sym)
        print(f"{sym:<6}{s['trades']:>7}{s['win_rate_%']:>7}{s['profit_factor']:>6}"
              f"{s['net_return_%(after fees)']:>8}{s['max_drawdown_%']:>8}"
              f"{s['buy_hold_return_%']:>10}  {'YES' if ok else 'no'}")

    print(f"\nEDGE-POSITIVE BASKET ({len(keep)}): {' '.join(keep)}")
    print(f"(gate: win>={MIN_WIN}% AND >={MIN_TRADES} trades AND net>0)")


if __name__ == "__main__":
    main()
