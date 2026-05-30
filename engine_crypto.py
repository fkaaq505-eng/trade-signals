"""
Run engine.py strategies (RSI2/VWAP/BB/trend) on 24h crypto data.

Key adaptation: session="all" bypasses the US-RTH filter that would kill 83% of
crypto bars. All other logic (fees, EOD-flat, 70/30 split) is unchanged.
Fee = 10 bps / side (crypto taker rate).

Usage:
    python engine_crypto.py btc_5m.csv rsi2
    python engine_crypto.py btc_5m.csv vwap
    python engine_crypto.py btc_5m.csv bb
    python engine_crypto.py btc_5m.csv trend
    python engine_crypto.py btc_5m.csv all    # run all 4
"""

from __future__ import annotations

import sys

import pandas as pd

from data_csv import load_csv
from engine import backtest

FEE_BPS = 10.0
TRAIN_FRAC = 0.70
STRATS = ["meanrev", "vwap", "bb", "trend"]


def _run_strategy(df: pd.DataFrame, strategy: str) -> dict:
    trades, _ = backtest(
        df,
        strategy=strategy,
        fee_bps=FEE_BPS,
        session="all",          # no session gate — crypto trades 24h
        eod_flat=True,          # flatten at end of each UTC day
        max_hold_hours=8.0,     # crypto: cap hold at 8h (one session length)
    )

    split_date = None
    if trades:
        dates = sorted({t.entry_date[:10] for t in trades})
        split_date = dates[int(len(dates) * TRAIN_FRAC)]

    is_trades = [t for t in trades if t.entry_date[:10] < split_date] if split_date else []
    oos_trades = [t for t in trades if t.entry_date[:10] >= split_date] if split_date else []

    def _seg(tl):
        if not tl:
            return {"n": 0, "win%": 0.0, "net_expR": 0.0, "net_totalR": 0.0,
                    "net_exp%": 0.0}
        wins = sum(1 for t in tl if t.pnl_pct > 0)
        net_r = [t.r_multiple for t in tl]
        # The MONEY truth: per-trade % return AFTER the round-turn fee. R-multiple
        # can be positive while % is negative (a few small-risk-distance winners
        # inflate R) — so report both; % is what the account actually earns.
        rt = 2.0 * FEE_BPS / 10_000.0
        net_pct = [((1.0 + t.pnl_pct / 100.0) * (1.0 - rt) - 1.0) * 100.0 for t in tl]
        return {
            "n": len(tl),
            "win%": round(100 * wins / len(tl), 1),
            "net_expR": round(sum(net_r) / len(net_r), 4),
            "net_totalR": round(sum(net_r), 1),
            "net_exp%": round(sum(net_pct) / len(net_pct), 4),
        }

    return {
        "strategy": strategy,
        "split_date": split_date,
        "in_sample": _seg(is_trades),
        "oos": _seg(oos_trades),
    }


def _print_result(r: dict, src: str) -> None:
    print(f"\n=== {r['strategy'].upper()} CRYPTO ({src}, session=all, "
          f"fee={FEE_BPS}bps/side, eod-flat) ===")
    print(f"train < {r['split_date']} | OOS >= {r['split_date']}\n")
    print(f"{'segment':<9}{'trades':>8}{'win%':>8}{'net_expR':>10}{'net_exp%':>10}{'net_totalR':>12}")
    print("-" * 57)
    for name, seg in (("IN-SAMP", r["in_sample"]), ("OOS", r["oos"])):
        print(f"{name:<9}{seg['n']:>8}{seg['win%']:>8}{seg['net_expR']:>10}"
              f"{seg['net_exp%']:>10}{seg['net_totalR']:>12}")
    oos = r["oos"]
    print("\n--- verdict ---")
    if oos["n"] == 0:
        print("  No OOS trades generated.")
    elif oos["net_exp%"] > 0:
        print(f"  OOS net {oos['net_exp%']:+.4f}%/trade AND {oos['net_expR']:+.4f} R both > 0 "
              f"— surprising; scrutinize 3x for look-ahead before trusting.")
    elif oos["net_expR"] > 0:
        print(f"  OOS net {oos['net_expR']:+.4f} R/trade > 0 BUT {oos['net_exp%']:+.4f}%/trade <= 0 "
              f"— R-positive / money-NEGATIVE. Risk-weighting illusion, NOT an edge.")
    else:
        print(f"  OOS net {oos['net_exp%']:+.4f}%/trade ({oos['net_expR']:+.4f} R) <= 0 "
              f"— no edge after {FEE_BPS}bps/side taker fees.")


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "btc_5m.csv"
    strat_arg = sys.argv[2].lower() if len(sys.argv) > 2 else "all"

    df = load_csv(src)
    run_list = STRATS if strat_arg == "all" else [strat_arg]

    for s in run_list:
        r = _run_strategy(df, s)
        _print_result(r, src)


if __name__ == "__main__":
    main()
