"""
ORB out-of-sample harness for 24h crypto markets.

Mirrors orb_oos.py but:
  - No US-RTH session filter (crypto data is all 24h).
  - "Day" = UTC calendar day; opening range = first OR_MINUTES of each UTC day.
  - Fee = 10 bps / side (crypto taker rate).
  - 70/30 OOS split by day count.

Reuses orb.py's backtest_orb_records() — no code duplication.
Does NOT modify orb_oos.py or orb.py.

Usage:
    python orb_crypto.py btc_5m.csv
    python orb_crypto.py eth_5m.csv
"""

from __future__ import annotations

import sys

import pandas as pd

from data_csv import load_csv
from orb import backtest_orb_records

FEE_BPS = 10.0     # per side; crypto taker. Round-turn = 20 bps.
TRAIN_FRAC = 0.70


def _segment(records, fee_bps: float) -> dict | None:
    n = len(records)
    if n == 0:
        return None
    round_turn = 2.0 * fee_bps / 10_000.0
    gross = [t.r for t in records]
    net = [t.r - round_turn * t.entry / t.rng for t in records]
    wins = sum(1 for g in gross if g > 0)
    equity = peak = drawdown = 0.0
    for r in net:
        equity += r
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return {
        "trades": n,
        "win_%": round(100.0 * wins / n, 1),
        "gross_expR": round(sum(gross) / n, 4),
        "net_expR": round(sum(net) / n, 4),
        "net_totalR": round(sum(net), 1),
        "maxDD_R": round(drawdown, 1),
    }


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "btc_5m.csv"
    df = load_csv(src)
    # No session filter — all UTC-day bars included
    records, _ = backtest_orb_records(df)
    if not records:
        print("no ORB trades (check data coverage)."); return

    days = sorted({t.date for t in records})
    split = days[int(len(days) * TRAIN_FRAC)]
    is_rec = [t for t in records if t.date < split]
    oos_rec = [t for t in records if t.date >= split]

    oos_px = df.loc[df.index >= pd.Timestamp(split), "Close"]
    oos_bh = (100.0 * (float(oos_px.iloc[-1]) / float(oos_px.iloc[0]) - 1.0)
              if len(oos_px) > 1 else 0.0)
    span = (df.index[-1] - df.index[0]).days

    print(f"\n=== ORB CRYPTO ({src}, ~{span}d / {span/365:.1f}y, 24h, "
          f"fee={FEE_BPS}bps/side) ===")
    print(f"train < {split} | OOS >= {split}")
    print(f"OOS buy-hold {oos_bh:+.1f}% (context only)\n")
    hdr = (f"{'segment':<10}{'trades':>8}{'win_%':>8}{'gross_expR':>12}"
           f"{'net_expR':>10}{'net_totalR':>12}{'maxDD_R':>9}")
    print(hdr); print("-" * len(hdr))
    is_seg = _segment(is_rec, FEE_BPS)
    oos_seg = _segment(oos_rec, FEE_BPS)
    for name, seg in (("IN-SAMP", is_seg), ("OOS", oos_seg)):
        if seg is None:
            print(f"{name:<10}{'(no trades)'}"); continue
        print(f"{name:<10}{seg['trades']:>8}{seg['win_%']:>8}{seg['gross_expR']:>12}"
              f"{seg['net_expR']:>10}{seg['net_totalR']:>12}{seg['maxDD_R']:>9}")

    oos_net = oos_seg["net_expR"] if oos_seg else 0.0
    print("\n--- verdict ---")
    if oos_net > 0:
        print(f"  OOS net {oos_net:+.4f} R/trade AFTER {FEE_BPS}bps/side > 0.")
        print("  Surprising — scrutinize for look-ahead before trusting.")
    else:
        print(f"  OOS net {oos_net:+.4f} R/trade AFTER {FEE_BPS}bps/side <= 0.")
        print("  ORB has NO edge on crypto after taker fees.")


if __name__ == "__main__":
    main()
