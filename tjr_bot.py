"""
TJR / "Path to Profitability" model, mechanized and tested out-of-sample on real
5-minute data. Built from the transcripts of the 14-video series.

TJR's tradeable core (the codeable part — the rest of the series is mindset/"flow
state", which a bot cannot have):
  1. Liquidity sits at session highs/lows; price RAIDS it (stop-hunt) then reverses.
  2. After the raid, a Break of Structure + a Fair Value Gap = the entry confluence.
  3. Stop goes past the raid extreme; target = the OPPOSITE liquidity.

Honest adaptation: TJR trades NQ FUTURES (24h, real Asia/London sessions). Stock
ETFs only trade RTH and Alpaca has no futures, so the liquidity pool here is the
PRIOR-DAY high/low (PDH/PDL) — the cleanest stock analog of "session liquidity".
Same engine (raid -> FVG reversal -> opposite-liquidity target), adapted hours.

Per RTH day, first setup only, EOD-flat, fee charged in R, 70/30 out-of-sample:
  - raid PDH (high>PDH) -> look for a BEARISH FVG (displacement down) -> SHORT at it,
    stop = highest high since the raid, target = PDL.
  - raid PDL (low<PDL)  -> BULLISH FVG -> LONG, stop = lowest low since raid, target = PDH.

    python tjr_bot.py spy_5m.csv
    python tjr_bot.py qqq_5m.csv     # Nasdaq = closest to TJR's NQ

*** A faithful MECHANICAL proxy. Expect gross edge < fees, like every intraday
    test in this repo. The discretionary "feel" is not in here and cannot be. ***
"""

from __future__ import annotations

import sys

from data_csv import load_csv
from sessions import in_session_mask

FEE_BPS = 1.0       # per side; round-turn = 2x
TRAIN = 0.70
MAX_R = 10.0        # cap absurd opposite-liquidity targets (sanity, not a tuned knob)


def _prior_day_levels(by_day: dict, days: list) -> dict:
    """{day: (PDH, PDL)} from the previous day's RTH high/low."""
    out = {}
    for i in range(1, len(days)):
        prev = by_day[days[i - 1]]
        out[days[i]] = (max(float(b["High"]) for _, b in prev),
                        min(float(b["Low"]) for _, b in prev))
    return out


def _day_trade(bars, pdh: float, pdl: float):
    """First raid->FVG-reversal setup of the day, then SIMULATE the trade forward
    (stop vs target, whichever the path hits first; else EOD-flat). Returns net R
    after fees, or None if no setup. No look-ahead: entry at the FVG bar's close,
    outcome decided only by subsequent bars."""
    round_turn = 2.0 * FEE_BPS / 10_000.0
    raided = extreme = None
    side = entry = stop = target = risk = None
    win = []
    for _, b in bars:
        hi, lo, cl = float(b["High"]), float(b["Low"]), float(b["Close"])

        if side is None:                                  # --- detection phase ---
            win.append((hi, lo, cl))
            if len(win) > 3:
                win.pop(0)
            if raided is None:
                if hi > pdh:
                    raided, extreme = "high", hi
                elif lo < pdl:
                    raided, extreme = "low", lo
                continue
            extreme = max(extreme, hi) if raided == "high" else min(extreme, lo)
            if len(win) < 3:
                continue
            (h1, l1, _), _, (h3, l3, _) = win
            if raided == "high" and l1 > h3:              # bearish FVG -> short
                side, entry, stop, target = "short", cl, extreme, pdl
                risk = stop - entry
            elif raided == "low" and h1 < l3:             # bullish FVG -> long
                side, entry, stop, target = "long", cl, extreme, pdh
                risk = entry - stop
            if side and (risk is None or risk <= 0):
                return None                               # invalid geometry, skip day
            continue

        # --- simulation phase (bars after entry) ---
        fee_r = round_turn * entry / risk                 # round-turn cost in R units
        if side == "short":
            if hi >= stop:
                return -1.0 - fee_r
            if lo <= target:
                return min((entry - target) / risk, MAX_R) - fee_r
        else:
            if lo <= stop:
                return -1.0 - fee_r
            if hi >= target:
                return min((target - entry) / risk, MAX_R) - fee_r

    if side is None:
        return None
    last = float(bars[-1][1]["Close"])                    # EOD-flat, neither hit
    fee_r = round_turn * entry / risk
    gross = ((last - entry) if side == "long" else (entry - last)) / risk
    return max(min(gross, MAX_R), -1.0) - fee_r


def run(df) -> list[tuple]:
    rth = df[in_session_mask(df.index, "us")]
    by_day: dict = {}
    for ts, row in rth.iterrows():
        by_day.setdefault(ts.date(), []).append((ts, row))
    days = sorted(by_day)
    levels = _prior_day_levels(by_day, days)

    trades = []
    for day in days:
        if day not in levels:
            continue
        pdh, pdl = levels[day]
        r = _day_trade(by_day[day], pdh, pdl)
        if r is not None:
            trades.append((str(day), r))
    return trades


def _seg(ts: list) -> dict:
    net = [r for _, r in ts]               # r is already net of fees (from _day_trade)
    wins = sum(1 for r in net if r > 0)
    return {"n": len(ts), "win%": round(100 * wins / len(ts), 1) if ts else 0.0,
            "expR": round(sum(net) / len(net), 4) if net else 0.0,
            "totalR": round(sum(net), 1)}


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "spy_5m.csv"
    ts = run(load_csv(src))
    if len(ts) < 20:
        print(f"only {len(ts)} setups — too few to judge."); return
    days = sorted({t[0] for t in ts})
    cut = days[int(len(days) * TRAIN)]
    is_t = [t for t in ts if t[0] < cut]
    oos_t = [t for t in ts if t[0] >= cut]

    print(f"\n=== TJR model (mechanized) — {src}, PDH/PDL raid -> FVG reversal, "
          f"EOD-flat, fee {FEE_BPS}bps/side ===")
    print(f"train < {cut} | OOS >= {cut}\n")
    print(f"{'segment':<9}{'setups':>8}{'win%':>8}{'net_expR':>10}{'net_totalR':>12}")
    print("-" * 47)
    for name, seg in (("IN-SAMP", _seg(is_t)), ("OOS", _seg(oos_t))):
        print(f"{name:<9}{seg['n']:>8}{seg['win%']:>8}{seg['expR']:>10}{seg['totalR']:>12}")

    oos = _seg(oos_t)
    print("\n--- verdict ---")
    if oos["expR"] > 0:
        print(f"  OOS {oos['expR']:+.4f} R/trade > 0 — surprising; scrutinize hard before any trust.")
    else:
        print(f"  OOS {oos['expR']:+.4f} R/trade <= 0 — TJR's mechanical model has NO edge after")
        print("  fees on real 5m data. Same verdict as ORB/RSI2/VWAP/ICT-sweep. The series'")
        print("  value is discipline/psychology, not a codeable money edge. Log it in journal.py.")


if __name__ == "__main__":
    main()
