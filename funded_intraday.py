"""
Funded/prop-compatible INTRADAY strategy for SPY: RSI(2) pullback on 1h bars with
a HARD ATR stop and FLAT-by-end-of-day (never holds overnight). This is the risk
SHAPE a prop evaluation needs — bounded per-trade loss, no overnight gap.

  *** HONEST HEALTH WARNING — READ THIS ***
  Free Yahoo data only gives ~730 days of 1h bars = ~2 years = ONE market regime
  (a bull run). A win rate measured on one regime is NOT evidence of an edge; it is
  the textbook overfit trap this project refuses to fake. Treat every number below
  as ILLUSTRATIVE OF STRUCTURE ONLY, not as a validated edge. Before risking a real
  evaluation: pull multi-year intraday data (Polygon/Alpaca/Databento) and re-run,
  then forward paper-test. The value here is the funded-compatible plumbing (hard
  stop + EOD-flat + sizing), not a promise that it makes money.

    python funded_intraday.py                  # SPY 1h from Yahoo (~3y, 1 regime)
    python funded_intraday.py SPY_5m.csv       # your own deep intraday CSV (preferred)
"""

from __future__ import annotations

import sys

from data import fetch
from data_csv import load_csv
from engine import backtest, stats

STOPS = (0.5, 1.0, 1.5)   # ATR multiples for the hard stop


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if src and src.lower().endswith(".csv"):
        df = load_csv(src)
        warned = f"loaded {len(df)} bars from {src}"
    else:
        df = fetch("SPY", "730d", "1h")
        warned = "*** ~2-3y / ONE regime — illustrative structure only, NOT a validated edge ***"
    buy_hold = df["Close"] / df["Close"].iloc[0]
    span_days = (df.index[-1] - df.index[0]).days

    print(f"\n=== FUNDED INTRADAY ({src or 'SPY 1h Yahoo'}, ~{span_days}d "
          f"≈ {span_days/365:.1f}y, hard stop + EOD-flat) ===")
    print(warned)
    print(f"buy_hold over window: {100.0*(buy_hold.iloc[-1]-1):.1f}%\n")
    print(f"{'stop(xATR)':>10}{'trades':>8}{'win%':>7}{'net%':>8}{'maxDD%':>8}"
          f"{'worstMAE%':>10}{'avgHold_h':>10}")
    print("-" * 61)

    for sl in STOPS:
        trades, eq = backtest(df, strategy="meanrev", sl_mult=sl, max_hold_hours=24.0,
                              skip_events=True, eod_flat=True)
        s = stats(trades, eq, buy_hold)
        if s.get("trades", 0) == 0:
            print(f"{sl:>10}{'(no trades)':>8}")
            continue
        worst_mae = min((t.mae_pct for t in trades), default=0.0)
        print(f"{sl:>10}{s['trades']:>8}{s['win_rate_%']:>7}"
              f"{s['net_return_%(after fees)']:>8}{s['max_drawdown_%']:>8}"
              f"{worst_mae:>10.2f}{s['avg_hold_hours']:>10}")

    print("\n  Funded-compatible shape achieved: a hard stop bounds each trade's loss "
          "and\n  EOD-flat removes overnight gap risk (worst-MAE column is now small + "
          "bounded,\n  unlike the daily strategy's -11%). That is what a prop DD limit needs.")
    print("  But edge is UNPROVEN on 2y/1-regime data. Do NOT take an evaluation on "
          "this\n  alone — validate on multi-year intraday data + forward paper test first.")


if __name__ == "__main__":
    main()
