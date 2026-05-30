"""
ICT sweep-reversal model adapted for 24h crypto markets.

Identical logic to ict_sweep.py BUT:
  - No US-RTH session filter (crypto never closes; filtering to RTH hours would
    chop 83% of the data and break the "manipulation window" concept entirely).
  - "Day" is defined as a UTC calendar day 00:00–23:59, consistent with how
    Asia / London / NY sessions are anchored to UTC dates.
  - Opening range = first OR_MIN minutes of the UTC day (midnight open).
  - Fee assumption: 10 bps per side (0.10%) taker fee — realistic Binance/Coinbase
    taker rate; far higher than the 1 bps used in stock tests. This is the honest
    bar for crypto: unless you trade maker-only you're paying ~10 bps/side.

Do NOT import or modify ict_sweep.py — this is a parallel file.

Usage:
    python ict_sweep_crypto.py btc_5m.csv
    python ict_sweep_crypto.py eth_5m.csv
"""

from __future__ import annotations

import sys

from data_csv import load_csv

OR_MIN = 20          # opening-range / "manipulation" window in minutes (same as original)
FEE_BPS = 10.0       # per side; crypto taker fee. Round-turn = 20 bps.
TRAIN = 0.70


def _step_min(idx) -> int:
    diffs = [(idx[i + 1] - idx[i]).total_seconds()
             for i in range(min(50, len(idx) - 1))]
    return max(1, int(min(d for d in diffs if d > 0) // 60))


def run(df) -> list[tuple]:
    """
    Returns list of (date_str, r_gross, entry_price, risk_points).
    r_gross is the raw R multiple before fee deduction (fee applied in _seg).
    No session filter: every UTC-day bar is included.
    """
    step = _step_min(df.index)
    or_bars = max(1, OR_MIN // step)
    by_day: dict = {}
    for ts, row in df.iterrows():
        by_day.setdefault(ts.date(), []).append((ts, row))

    trades = []
    for day in sorted(by_day):
        bars = by_day[day]
        if len(bars) <= or_bars + 1:
            continue
        opening = bars[:or_bars]
        or_high = max(float(b["High"]) for _, b in opening)
        or_low = min(float(b["Low"]) for _, b in opening)
        rest = bars[or_bars:]
        swept_hi = swept_lo = False
        side = entry = stop = target = None

        for _, b in rest:
            hi, lo, cl = float(b["High"]), float(b["Low"]), float(b["Close"])
            if side is None:
                if hi > or_high:
                    swept_hi = True
                if lo < or_low:
                    swept_lo = True
                if swept_hi and cl < or_high:              # failed high sweep -> short
                    side, entry, stop, target = "short", cl, max(hi, or_high), or_low
                elif swept_lo and cl > or_low:             # failed low sweep -> long
                    side, entry, stop, target = "long", cl, min(lo, or_low), or_high
                continue
            if side == "short":
                if hi >= stop:
                    trades.append((str(day), -1.0, entry, stop - entry)); break
                if lo <= target:
                    trades.append((str(day), (entry - target) / (stop - entry), entry, stop - entry)); break
            else:
                if lo <= stop:
                    trades.append((str(day), -1.0, entry, entry - stop)); break
                if hi >= target:
                    trades.append((str(day), (target - entry) / (entry - stop), entry, entry - stop)); break
        else:
            if side is not None:            # EOD-flat (end of UTC day)
                last = float(rest[-1][1]["Close"])
                risk = abs(entry - stop)
                r = ((last - entry) if side == "long" else (entry - last)) / risk if risk > 0 else 0.0
                trades.append((str(day), r, entry, risk))
    return trades


def _seg(ts: list, fee_bps: float) -> dict:
    """Net expectancy after round-turn fees (expressed in R units)."""
    rt = 2.0 * fee_bps / 10_000.0
    net = [r - rt * e / k for _, r, e, k in ts if k > 0]
    wins = sum(1 for _, r, _, _ in ts if r > 0)
    return {
        "n": len(ts),
        "win%": round(100 * wins / len(ts), 1) if ts else 0,
        "net_expR": round(sum(net) / len(net), 4) if net else 0.0,
        "net_totalR": round(sum(net), 1),
    }


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "btc_5m.csv"
    df = load_csv(src)
    # NO session filter — 24h crypto data used in full
    ts = run(df)
    if not ts:
        print("no sweep-reversal trades."); return

    days = sorted({t[0] for t in ts})
    cut = days[int(len(days) * TRAIN)]
    is_t = [t for t in ts if t[0] < cut]
    oos_t = [t for t in ts if t[0] >= cut]

    # OOS buy-hold over held-out window
    oos_df = df[df.index >= cut]
    bh = (100.0 * (float(oos_df["Close"].iloc[-1]) / float(oos_df["Close"].iloc[0]) - 1.0)
          if len(oos_df) > 1 else 0.0)

    print(f"\n=== ICT sweep-reversal CRYPTO ({src}, 24h NO filter, OR={OR_MIN}m, "
          f"EOD-flat, fee={FEE_BPS}bps/side) ===")
    print(f"train < {cut} | OOS >= {cut}")
    print(f"OOS buy-hold: {bh:+.1f}% (context only)\n")
    print(f"{'segment':<9}{'trades':>8}{'win%':>8}{'net_expR':>10}{'net_totalR':>12}")
    print("-" * 47)
    for name, seg in (("IN-SAMP", _seg(is_t, FEE_BPS)), ("OOS", _seg(oos_t, FEE_BPS))):
        print(f"{name:<9}{seg['n']:>8}{seg['win%']:>8}{seg['net_expR']:>10}{seg['net_totalR']:>12}")

    oos = _seg(oos_t, FEE_BPS)
    print("\n--- verdict ---")
    if oos["net_expR"] > 0:
        print(f"  OOS net {oos['net_expR']:+.4f} R/trade > 0 — UNUSUAL. Check for look-ahead bugs")
        print("  before trusting. Fee = {FEE_BPS} bps/side already applied.")
    else:
        print(f"  OOS net {oos['net_expR']:+.4f} R/trade <= 0 — ICT sweep-reversal has NO edge on")
        print(f"  24h crypto data after {FEE_BPS} bps/side taker fees.")


if __name__ == "__main__":
    main()
