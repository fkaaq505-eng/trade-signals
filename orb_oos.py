"""
Out-of-sample ORB backtest on REAL deep intraday data (Alpaca 5-min CSV).

Tests the funded/prop archetype the research points to — Opening Range Breakout
with strict risk rules — the HONEST way. The four families tested before (RSI2,
VWAP, Bollinger) were all MEAN REVERSION; ORB is the momentum/breakout side that
consistently-funded futures traders actually use, and it was never run on the deep
5-minute data out-of-sample. This closes that gap:

  - regular session only (9:30-16:00 ET, DST-aware) so the "opening range" is the
    TRUE market open, not pre-market noise,
  - first 30 min = opening range; breakout = entry; stop = opposite side of the
    range (= 1R); target = RR x range; one trade/day; trend filter; EOD-flat
    (now mandatory: Apex 4.0 + Topstep ban overnight as of 2026-03-01),
  - train on the older 70% of days, test on the held-out recent 30%,
  - expectancy reported GROSS and NET of round-turn fees, in R.

The funded bar is POSITIVE EXPECTANCY AFTER FEES out-of-sample. Buy-hold is NOT the
benchmark: a funded intraday account cannot hold overnight, so buy-hold is
unreachable here — it is printed for context only.

    python orb_oos.py spy_5m.csv          # the real Alpaca 5-min data (run this)
    python orb_oos.py                      # SPY 15m Yahoo (~60d, illustrative only)
"""

from __future__ import annotations

import sys

import pandas as pd

from data import fetch
from data_csv import load_csv
from orb import OR_MINUTES, RR, USE_TREND, backtest_orb_records
from sessions import in_session_mask

FEE_BPS = 1.0   # per side; round-turn = 2x. Matches the rest of the repo's fee model.
TRAIN_FRAC = 0.70


def _segment(records: list, fee_bps: float) -> dict | None:
    """Win%, gross/net expectancy (R), total + max drawdown (R) for one segment.

    Fee in R = round-turn cost in price points / range, since the opening range is
    exactly 1R. round_turn = 2 x fee_bps covers both legs (entry + exit)."""
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
    src = sys.argv[1] if len(sys.argv) > 1 else None
    df = load_csv(src) if src and src.lower().endswith(".csv") else fetch("SPY", "60d", "15m")

    # Regular session only — the opening range must be the real 9:30 ET open, not
    # the thin pre-market bars Alpaca includes by default.
    rth = df[in_session_mask(df.index, "us")]
    records, _ = backtest_orb_records(rth)
    if not records:
        print("no ORB trades formed (check the data covers the regular session).")
        return

    # Split by calendar day: older 70% in-sample, recent 30% held out (OOS).
    days = sorted({t.date for t in records})
    split = days[int(len(days) * TRAIN_FRAC)]
    is_rec = [t for t in records if t.date < split]
    oos_rec = [t for t in records if t.date >= split]

    # OOS buy-hold over the held-out window (context only; unreachable intraday).
    oos_px = rth.loc[rth.index >= pd.Timestamp(split), "Close"]
    oos_bh = 100.0 * (oos_px.iloc[-1] / oos_px.iloc[0] - 1.0) if len(oos_px) > 1 else 0.0
    span = (df.index[-1] - df.index[0]).days

    print(f"\n=== ORB OUT-OF-SAMPLE ({src or 'SPY 15m Yahoo'}, ~{span}d / ~{span/365:.1f}y, "
          f"RTH only, OR={OR_MINUTES}m, RR={RR}, "
          f"trend-filter={'on' if USE_TREND else 'off'}, EOD-flat, fee={FEE_BPS}bps/side) ===")
    print(f"train days < {split}  |  OOS days >= {split}  |  "
          f"OOS buy-hold {oos_bh:+.1f}% (context only — unreachable in a funded intraday acct)\n")

    hdr = (f"{'segment':<10}{'trades':>8}{'win_%':>8}{'gross_expR':>12}"
           f"{'net_expR':>10}{'net_totalR':>12}{'maxDD_R':>9}")
    print(hdr)
    print("-" * len(hdr))
    is_seg, oos_seg = _segment(is_rec, FEE_BPS), _segment(oos_rec, FEE_BPS)
    for name, seg in (("IN-SAMP", is_seg), ("OOS", oos_seg)):
        if seg is None:
            print(f"{name:<10}{'(no trades)':>8}")
            continue
        print(f"{name:<10}{seg['trades']:>8}{seg['win_%']:>8}{seg['gross_expR']:>12}"
              f"{seg['net_expR']:>10}{seg['net_totalR']:>12}{seg['maxDD_R']:>9}")

    print("\n--- verdict ---")
    oos_net = oos_seg["net_expR"] if oos_seg else 0.0
    if oos_net > 0:
        print(f"  OOS net expectancy = {oos_net:+.4f} R/trade AFTER fees > 0.")
        print("  ORB shows a (small) surviving edge on REAL data. Confirm with forward")
        print("  paper-testing against one firm's exact drawdown limits before trusting it.")
    else:
        print(f"  OOS net expectancy = {oos_net:+.4f} R/trade AFTER fees <= 0.")
        print("  ORB has NO surviving edge on real 5-min SPY out-of-sample — same verdict")
        print("  as the mean-reversion families. The funded edge is risk discipline, not")
        print("  this entry. (Try RR/OR_MINUTES/trend-filter in orb.py, but expect the same.)")


if __name__ == "__main__":
    main()
