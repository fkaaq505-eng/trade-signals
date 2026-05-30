"""
Opening Range Breakout (ORB) — the standard funded/prop intraday setup, built with
the risk rules the evidence says actually pass challenges (one setup/day, defined
stop = range opposite side, R:R target, flat by close, fixed % risk per trade).

  *** HONEST HEALTH WARNING ***
  Research is clear that (a) ORB's edge is weak and eroding (~67% of breakouts are
  false), and (b) what passes funded challenges is RISK MANAGEMENT, not the entry.
  Free Yahoo gives only ~60 days of 15m bars = far too little to validate an edge.
  Numbers below are ILLUSTRATIVE of the mechanics, NOT proof of profit. Feed real
  multi-year intraday data (CSV) and forward paper-test before risking an account.

    python orb.py                      # SPY 15m from Yahoo (~60d, illustrative)
    python orb.py SPY_15m.csv          # your own deep intraday CSV (preferred)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from data import fetch
from data_csv import load_csv

OR_MINUTES = 30      # opening range = first 30 min of the session
RR = 1.5             # target = RR x range; stop = the opposite side of the range
RISK_PCT = 1.0       # % of account risked per trade (evidence: winners use 0.5-1%)
ACCOUNT = 50_000.0
USE_TREND = True     # only take breakouts in the prior-day direction (filter)


def _bar_minutes(idx) -> int:
    diffs = (idx[1:] - idx[:-1])
    secs = min(d.total_seconds() for d in diffs if d.total_seconds() > 0)
    return max(1, int(secs // 60))


@dataclass(frozen=True)
class OrbTrade:
    """One day's ORB result. r = gross R-multiple (before fees); rng = the opening
    range in price points = exactly 1R of risk (entry to stop)."""
    date: str
    side: str          # "long" | "short"
    r: float
    entry: float
    rng: float


def _run(df):
    """Core ORB sim: one trade/day. Returns (list[OrbTrade], today's plan dict)."""
    step = _bar_minutes(df.index)
    or_bars = max(1, OR_MINUTES // step)
    by_day = {}
    for ts, row in df.iterrows():
        by_day.setdefault(ts.date(), []).append((ts, row))

    results, prev_close, plan = [], None, None
    for day in sorted(by_day):
        bars = by_day[day]
        if len(bars) <= or_bars:
            prev_close = bars[-1][1]["Close"]
            continue
        opening = bars[:or_bars]
        or_high = max(float(b["High"]) for _, b in opening)
        or_low = min(float(b["Low"]) for _, b in opening)
        rng = or_high - or_low
        day_open = float(opening[0][1]["Open"])
        long_ok = (not USE_TREND) or prev_close is None or day_open >= float(prev_close)
        short_ok = (not USE_TREND) or prev_close is None or day_open <= float(prev_close)

        plan = {"date": str(day), "or_high": round(or_high, 2), "or_low": round(or_low, 2),
                "range": round(rng, 2), "long_ok": long_ok, "short_ok": short_ok,
                "long_target": round(or_high + RR * rng, 2),
                "short_target": round(or_low - RR * rng, 2)}

        if rng > 0:
            trade = _simulate_day(day, bars[or_bars:], or_high, or_low, rng, long_ok, short_ok)
            if trade is not None:
                results.append(trade)
        prev_close = bars[-1][1]["Close"]

    return results, plan


def backtest_orb(df):
    """Back-compat shape: (list of gross R-multiples, today's plan dict)."""
    results, plan = _run(df)
    return [t.r for t in results], plan


def backtest_orb_records(df):
    """Detailed shape for OOS + fee analysis: (list[OrbTrade], today's plan dict)."""
    return _run(df)


def _simulate_day(day, rest, or_high, or_low, rng, long_ok, short_ok):
    side = entry = stop = target = None
    for _, b in rest:
        hi, lo, close = float(b["High"]), float(b["Low"]), float(b["Close"])
        if side is None:
            if long_ok and hi >= or_high:
                side, entry, stop, target = "long", or_high, or_low, or_high + RR * rng
            elif short_ok and lo <= or_low:
                side, entry, stop, target = "short", or_low, or_high, or_low - RR * rng
            continue
        if side == "long":
            if lo <= stop:
                return OrbTrade(str(day), side, -1.0, entry, rng)
            if hi >= target:
                return OrbTrade(str(day), side, RR, entry, rng)
        else:
            if hi >= stop:
                return OrbTrade(str(day), side, -1.0, entry, rng)
            if lo <= target:
                return OrbTrade(str(day), side, RR, entry, rng)
    if side is None:
        return None                      # no breakout that day -> no trade
    last = float(rest[-1][1]["Close"])   # EOD-flat at the close
    r = ((last - entry) if side == "long" else (entry - last)) / rng
    return OrbTrade(str(day), side, r, entry, rng)


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else None
    df = load_csv(src) if src and src.lower().endswith(".csv") else fetch("SPY", "60d", "15m")
    results, plan = backtest_orb(df)
    span = (df.index[-1] - df.index[0]).days

    print(f"\n=== ORB ({src or 'SPY 15m Yahoo'}, ~{span}d, OR={OR_MINUTES}m, RR={RR}, "
          f"trend-filter={'on' if USE_TREND else 'off'}) ===")
    print("*** illustrative mechanics only — NOT a validated edge (see warning) ***")
    if not results:
        print("no trades.")
        return
    wins = [r for r in results if r > 0]
    total_r = sum(results)
    # Max drawdown in R along the equity-in-R curve.
    eq = peak = dd = 0.0
    for r in results:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    print(f"  trades            {len(results)}  (~1/day, {len([r for r in results if r==0])} scratch)")
    print(f"  win_rate_%        {100*len(wins)/len(results):.1f}")
    print(f"  expectancy_R      {total_r/len(results):+.3f}   (avg R per trade; >0 = edge)")
    print(f"  total_R           {total_r:+.1f}")
    print(f"  maxDD_R           {dd:.1f}")
    print(f"  risk/trade        {RISK_PCT}% of ${ACCOUNT:,.0f} = ${ACCOUNT*RISK_PCT/100:,.0f}")

    p = plan
    shares = (ACCOUNT * RISK_PCT / 100) / p["range"] if p["range"] else 0
    print(f"\n  --- latest day's plan ({p['date']}) ---")
    print(f"  opening range: {p['or_low']} - {p['or_high']}  (range {p['range']})")
    if p["long_ok"]:
        print(f"  LONG  stop-buy > {p['or_high']}  | stop {p['or_low']} | target {p['long_target']}")
    if p["short_ok"]:
        print(f"  SHORT stop-sell < {p['or_low']}  | stop {p['or_high']} | target {p['short_target']}")
    print(f"  size for {RISK_PCT}% risk: ~{shares:.0f} SPY shares  ·  FLAT by close, no overnight")


if __name__ == "__main__":
    main()
