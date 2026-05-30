"""
Mechanical proxy for the ICT / TJR 'liquidity sweep + reversal' setup — the one
testable core of that day-trading tutorial (9:30-9:50 "manipulation"/sweep, then a
reversal). Tests whether FADING a swept opening range has an edge on real 5m SPY,
out-of-sample, after fees.

Per day (RTH only):
  - opening range = first OR_MIN minutes (9:30-9:50 default).
  - SHORT: a later bar's HIGH sweeps above or_high, then a bar CLOSES back below
    or_high -> short at that close; stop = the sweep high; target = or_low.
  - LONG: mirror (sweep below or_low, close back above -> long; stop = sweep low;
    target = or_high).
  - first valid sweep-reversal only; EOD-flat; R = (reward)/(risk).

Honest note: full ICT (FVG, BOS, order blocks, "adapt daily") is discretionary and
unfalsifiable — this is a faithful MECHANICAL proxy of its headline setup. Like every
intraday SPY test in this repo, expect gross edge < round-turn fees.

    python ict_sweep.py spy_5m.csv
"""

from __future__ import annotations

import sys

from data_csv import load_csv
from sessions import in_session_mask

OR_MIN = 20        # opening-range / "manipulation" window in minutes
FEE_BPS = 1.0      # per side; round-turn = 2x
TRAIN = 0.70


def _step_min(idx) -> int:
    diffs = [(idx[i + 1] - idx[i]).total_seconds() for i in range(min(50, len(idx) - 1))]
    return max(1, int(min(d for d in diffs if d > 0) // 60))


def run(df) -> list[tuple]:
    step = _step_min(df.index)
    or_bars = max(1, OR_MIN // step)
    by_day: dict = {}
    for ts, row in df.iterrows():
        by_day.setdefault(ts.date(), []).append((ts, row))

    trades = []   # (date, r_gross, entry, risk_points)
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
                if swept_hi and cl < or_high:                 # failed high -> fade short
                    side, entry, stop, target = "short", cl, max(hi, or_high), or_low
                elif swept_lo and cl > or_low:                # failed low -> fade long
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
            if side is not None:                               # EOD-flat, neither hit
                last = float(rest[-1][1]["Close"])
                risk = abs(entry - stop)
                r = ((last - entry) if side == "long" else (entry - last)) / risk if risk > 0 else 0.0
                trades.append((str(day), r, entry, risk))
    return trades


def _seg(ts: list, fee_bps: float) -> dict:
    rt = 2.0 * fee_bps / 10_000.0
    net = [r - rt * e / k for _, r, e, k in ts if k > 0]
    wins = sum(1 for _, r, _, _ in ts if r > 0)
    return {"n": len(ts), "win%": round(100 * wins / len(ts), 1) if ts else 0,
            "net_expR": round(sum(net) / len(net), 4) if net else 0.0,
            "net_totalR": round(sum(net), 1)}


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "spy_5m.csv"
    rth = load_csv(src)
    rth = rth[in_session_mask(rth.index, "us")]
    ts = run(rth)
    if not ts:
        print("no sweep-reversal trades."); return
    days = sorted({t[0] for t in ts})
    cut = days[int(len(days) * TRAIN)]
    is_t = [t for t in ts if t[0] < cut]
    oos_t = [t for t in ts if t[0] >= cut]

    print(f"\n=== ICT sweep-reversal ({src}, RTH, OR={OR_MIN}m, EOD-flat, fee={FEE_BPS}bps/side) ===")
    print(f"train < {cut} | OOS >= {cut}\n")
    print(f"{'segment':<9}{'trades':>8}{'win%':>8}{'net_expR':>10}{'net_totalR':>12}")
    print("-" * 47)
    for name, seg in (("IN-SAMP", _seg(is_t, FEE_BPS)), ("OOS", _seg(oos_t, FEE_BPS))):
        print(f"{name:<9}{seg['n']:>8}{seg['win%']:>8}{seg['net_expR']:>10}{seg['net_totalR']:>12}")
    oos = _seg(oos_t, FEE_BPS)
    print("\n--- verdict ---")
    if oos["net_expR"] > 0:
        print(f"  OOS net {oos['net_expR']:+.4f} R/trade > 0 — surprising; scrutinize before trusting.")
    else:
        print(f"  OOS net {oos['net_expR']:+.4f} R/trade <= 0 — the ICT sweep-reversal has NO edge")
        print("  on real 5m SPY after fees. Same verdict as ORB/RSI2/VWAP. 'Feel' isn't an edge.")


if __name__ == "__main__":
    main()
