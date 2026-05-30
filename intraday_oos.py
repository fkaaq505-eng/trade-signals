"""
Out-of-sample test for the funded intraday strategies on the deepest intraday data
free of an API key: ~2 years of 1h SPY bars. Trains on the older 70%, tests on the
held-out recent 30%, and reports IN-SAMPLE vs OUT-OF-SAMPLE win rate, expectancy
(avg % per trade) and net — so we see if any "accurate" strategy holds up live.

All funded-compatible: hard stop + flat-by-close.

    python intraday_oos.py                 # SPY 1h Yahoo (~2y, deepest keyless)
    python intraday_oos.py SPY_5m.csv      # your deep CSV (run this for real proof)

*** 1h/2y is still ONE regime. Honest but not conclusive. Real proof needs years
    of 5m/1m bars via a CSV (Alpaca/Polygon/TradingView export). ***
"""

from __future__ import annotations

import sys

import pandas as pd

from data import fetch
from data_csv import load_csv
from engine import backtest, stats

FEE_BPS = 1.0
CANDIDATES = [
    ("RSI2 1h", "meanrev", 1.0),
    ("RSI2 tighter", "meanrev", 0.5),
    ("VWAP 1h", "vwap", 1.0),
    ("Bollinger 1h", "bb", 1.0),
]


def equity_from(trades):
    round_turn = 2.0 * FEE_BPS / 10_000.0
    eq, curve = 1.0, []
    for t in trades:
        eq *= (1.0 + t.pnl_pct / 100.0) * (1.0 - round_turn)
        curve.append(eq)
    return pd.Series(curve or [1.0])


def seg_stats(trades, close):
    return stats(trades, equity_from(trades), close)


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else None
    df = load_csv(src) if src and src.lower().endswith(".csv") else fetch("SPY", "730d", "1h")
    cut = int(len(df) * 0.70)
    split_ts = df.index[cut]
    is_close = df.loc[df.index < split_ts, "Close"]
    oos_close = df.loc[df.index >= split_ts, "Close"]
    oos_bh = 100.0 * (oos_close.iloc[-1] / oos_close.iloc[0] - 1.0)
    span = (df.index[-1] - df.index[0]).days

    print(f"\n=== INTRADAY OUT-OF-SAMPLE ({src or 'SPY 1h Yahoo'}, ~{span}d, "
          f"hard stop + EOD-flat) ===")
    print(f"train < {str(split_ts)[:10]}  |  OOS held-out >= that  |  "
          f"OOS buy_hold {oos_bh:+.1f}%")
    note = (f"*** {len(df):,} bars over ~{span/365:.1f}y of REAL data ***" if src
            else "*** ~2y / one regime free Yahoo data — not conclusive ***")
    print(note + "\n")
    print(f"{'strategy':<14}{'IS_win%':>8}{'IS_exp%':>8}{'IS_net%':>8} | "
          f"{'OOS_win%':>9}{'OOS_exp%':>9}{'OOS_net%':>9}")
    print("-" * 70)

    verdict_ok = False
    for label, strat, sl in CANDIDATES:
        trades, _ = backtest(df, strategy=strat, sl_mult=sl, max_hold_hours=24.0,
                             skip_events=False, eod_flat=True)
        is_t = [t for t in trades if pd.Timestamp(t.entry_date) < split_ts]
        oos_t = [t for t in trades if pd.Timestamp(t.entry_date) >= split_ts]
        a, b = seg_stats(is_t, is_close), seg_stats(oos_t, oos_close)
        if a.get("trades", 0) == 0 or b.get("trades", 0) == 0:
            print(f"{label:<14}{'(too few trades in a segment)':>40}")
            continue
        print(f"{label:<14}{a['win_rate_%']:>8}{a['avg_trade_%']:>8}"
              f"{a['net_return_%(after fees)']:>8} | {b['win_rate_%']:>9}"
              f"{b['avg_trade_%']:>9}{b['net_return_%(after fees)']:>9}")
        # "Real" = positive expectancy OOS AND beats buy-hold OOS.
        if b["avg_trade_%"] > 0 and b["net_return_%(after fees)"] > oos_bh:
            verdict_ok = True

    print("\n--- verdict ---")
    if verdict_ok:
        print("  A strategy held positive expectancy OUT-OF-SAMPLE and beat buy-hold. "
              "Promising —\n  but confirm on years of finer (5m/1m) data before trusting it.")
    else:
        print("  No strategy is both positive AND beats buy-hold out of sample. On the "
              "deepest\n  free intraday data, there is NO validated edge here. Get real "
              "5m/1m data via CSV\n  to test further, or accept that retail intraday SPY "
              "has no easy edge.")


if __name__ == "__main__":
    main()
