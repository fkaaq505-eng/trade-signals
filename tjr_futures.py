"""
TJR / ICT session-liquidity + FVG reversal model adapted for REAL NQ/ES futures
and index CFD data (Dukascopy E_NQ-100, E_SandP-500).

Key differences from tjr_bot.py (stock-proxy version):
  - Liquidity pools = REAL session highs/lows (Asia, London, NY) instead of PDH/PDL.
  - No RTH-only filter — futures trade ~23h; all session bars are used.
  - Session definitions (UTC, DST-agnostic for simplicity):
      Asia    00:00-07:00 UTC  (Tokyo/Sydney)
      London  07:00-16:00 UTC  (includes EU/US overlap)
      NY AM   13:30-18:00 UTC  (NYSE open = 09:30 ET = 13:30 UTC in winter)
    In practice, a "NY-session pool" is the prior-NY-session's H/L, and we look
    for raids into that pool followed by a BOS+FVG during the next London or NY AM.
  - Fee model: realistic futures round-turn cost in R units.
      NQ: tick = 0.25 pt; commission ≈ $4.50 RT + ~1 tick slippage = 1.75 pts RT
      ES: tick = 0.25 pt; commission ≈ $4.50 RT + ~1 tick slippage = 0.50 pts RT
    We model fee as fixed R fraction derived from (fee_pts / risk_pts).
    For the Dukascopy CFD data (no exact contract spec) we use 3 bps round-turn
    as a conservative spread proxy. State this explicitly.

Strategy logic (same raid→FVG→simulate as tjr_bot.py, different pool source):
  Per trading "cycle" (one session window at a time):
    1. Identify the prior session's high (LH) and low (LL) as liquidity pools.
    2. After a bar's high exceeds LH (raid high) → look for a bearish FVG
       (candle[i-2].low > candle[i].high) → SHORT at that bar's close.
    3. After a bar's low goes below LL (raid low) → look for a bullish FVG
       (candle[i-2].high < candle[i].low) → LONG at close.
    4. Stop = beyond the raid extreme. Target = the OPPOSITE pool.
    5. Simulate bar-by-bar (stop-first priority). Max-hold = 8 h then flat.
    6. Fee charged in R.

OOS split: 70% train (older) / 30% test (recent) by calendar day.

Usage:
    python tjr_futures.py nqf_1h_730d.csv nq          # Yahoo NQ futures 1h
    python tjr_futures.py nq_cfd_5m_duka.csv nq_cfd   # Dukascopy NQ CFD 5m
    python tjr_futures.py esf_1h_730d.csv es          # Yahoo ES futures 1h
    python tjr_futures.py es_cfd_5m_duka.csv es_cfd   # Dukascopy ES CFD 5m
"""

from __future__ import annotations

import sys

import pandas as pd

from data_csv import load_csv

# ---------------------------------------------------------------------------
# Session window constants (UTC hour boundaries)
# ---------------------------------------------------------------------------
ASIA_OPEN_H    = 0
ASIA_CLOSE_H   = 7
LONDON_OPEN_H  = 7
LONDON_CLOSE_H = 16
NY_OPEN_H      = 13   # 09:30 ET ≈ 13:30 UTC (winter); we use 13 for simplicity
NY_CLOSE_H     = 20

# FVG window look-back
FVG_LOOKBACK = 3   # need 3 bars: the 3-candle FVG pattern

MAX_HOLD_BARS = 8 * 12   # 8 h * 12 bars/h at 5m; auto-capped in practice
MAX_R = 10.0             # cap wild opposite-pool targets

# 70/30 OOS split
TRAIN_FRAC = 0.70


# ---------------------------------------------------------------------------
# Fee model
# ---------------------------------------------------------------------------
def _fee_r(side: str, entry: float, risk: float, mode: str) -> float:
    """Round-turn cost in R units.

    mode='nq'  : NQ futures, 1.75 pts RT (commission + 1 tick slippage)
    mode='es'  : ES futures, 0.50 pts RT
    mode='cfd' : index CFD, 3 bps round-turn on entry price
    """
    if mode in ("nq", "nq_cfd"):
        rt_pts = 1.75    # NQ: $4.50 ÷ $5/tick * 0.25 + 0.25 tick slip ≈ 1.75 pts
    elif mode in ("es", "es_cfd"):
        rt_pts = 0.50    # ES: $4.50 ÷ $12.50/tick * 0.25 + 0.25 tick ≈ 0.50 pts
    else:
        rt_pts = 3.0 * entry / 10_000.0   # 3 bps fallback
    if risk <= 0:
        return 0.0
    return rt_pts / risk


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def _session_label(ts: pd.Timestamp) -> str:
    h = ts.hour
    if ASIA_OPEN_H <= h < ASIA_CLOSE_H:
        return "asia"
    if LONDON_OPEN_H <= h < LONDON_CLOSE_H:
        return "london"
    if NY_OPEN_H <= h < NY_CLOSE_H:
        return "ny"
    return "off"


def _session_hl(bars: list[tuple]) -> tuple[float, float]:
    """High and low of a bar list."""
    hi = max(float(b["High"]) for _, b in bars)
    lo = min(float(b["Low"]) for _, b in bars)
    return hi, lo


# ---------------------------------------------------------------------------
# Core trade simulation (no look-ahead)
# ---------------------------------------------------------------------------
def _simulate_trade(bars_after_entry: list[tuple], side: str, entry: float,
                    stop: float, target: float, risk: float, mode: str,
                    max_hold_bars: int) -> float:
    """Walk bars forward, return net R after fee. Stop is checked first."""
    fee = _fee_r(side, entry, risk, mode)
    for i, (_, b) in enumerate(bars_after_entry):
        if i >= max_hold_bars:
            last = float(b["Close"])
            gross = ((last - entry) if side == "long" else (entry - last)) / risk
            return max(min(gross, MAX_R), -1.0) - fee
        hi, lo = float(b["High"]), float(b["Low"])
        if side == "short":
            if hi >= stop:
                return -1.0 - fee
            if lo <= target:
                raw_r = (entry - target) / risk
                return min(raw_r, MAX_R) - fee
        else:
            if lo <= stop:
                return -1.0 - fee
            if hi >= target:
                raw_r = (target - entry) / risk
                return min(raw_r, MAX_R) - fee
    # Ran out of bars (EOD or end of data)
    if not bars_after_entry:
        return 0.0 - fee
    last = float(bars_after_entry[-1][1]["Close"])
    gross = ((last - entry) if side == "long" else (entry - last)) / risk
    return max(min(gross, MAX_R), -1.0) - fee


# ---------------------------------------------------------------------------
# Per-session setup scan
# ---------------------------------------------------------------------------
def _find_setup(bars: list[tuple], pool_hi: float, pool_lo: float,
                mode: str, max_hold_bars: int) -> float | None:
    """Scan bars for the first raid→FVG-reversal setup. Return net R or None."""
    raided: str | None = None   # "high" or "low"
    raid_extreme: float = 0.0
    window: list[tuple[float, float, float]] = []  # (hi, lo, cl) rolling 3-bar

    for i, (_, b) in enumerate(bars):
        hi, lo, cl = float(b["High"]), float(b["Low"]), float(b["Close"])

        if raided is None:
            window.append((hi, lo, cl))
            if len(window) > FVG_LOOKBACK:
                window.pop(0)
            if hi > pool_hi:
                raided = "high"
                raid_extreme = hi
            elif lo < pool_lo:
                raided = "low"
                raid_extreme = lo
            continue

        # Update raid extreme
        if raided == "high":
            raid_extreme = max(raid_extreme, hi)
        else:
            raid_extreme = min(raid_extreme, lo)

        window.append((hi, lo, cl))
        if len(window) > FVG_LOOKBACK:
            window.pop(0)
        if len(window) < FVG_LOOKBACK:
            continue

        h1, l1, _ = window[0]
        h3, l3, _ = window[2]

        if raided == "high" and l1 > h3:   # bearish FVG after high raid
            entry = cl
            stop = raid_extreme
            target = pool_lo
            risk = stop - entry
            if risk <= 0:
                return None
            return _simulate_trade(
                bars[i + 1:], "short", entry, stop, target, risk, mode, max_hold_bars
            )
        if raided == "low" and h1 < l3:    # bullish FVG after low raid
            entry = cl
            stop = raid_extreme
            target = pool_hi
            risk = entry - stop
            if risk <= 0:
                return None
            return _simulate_trade(
                bars[i + 1:], "long", entry, stop, target, risk, mode, max_hold_bars
            )

    return None   # no qualifying setup in this session window


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------
def run(df: pd.DataFrame, mode: str = "nq") -> list[tuple[str, float]]:
    """Return list of (date_str, net_R) for each trade found.

    Liquidity pools: prior London session's H/L for the London/NY cycle,
    prior NY session's H/L for the Asia cycle. We keep it simple:
    group all bars by calendar day, label each bar by session, and use
    the previous calendar-day's session extremes as the pools.
    """
    # Determine bar interval in minutes for max_hold_bars
    idx = df.index
    if len(idx) > 2:
        diffs = [(idx[j + 1] - idx[j]).total_seconds()
                 for j in range(min(50, len(idx) - 1)) if (idx[j + 1] - idx[j]).total_seconds() > 0]
        step_min = max(1, int(min(diffs) // 60))
    else:
        step_min = 60
    max_hold_bars = max(1, (8 * 60) // step_min)

    # Group bars by (date, session)
    sessions_by_day: dict[tuple, list] = {}
    for ts, row in df.iterrows():
        label = _session_label(ts)
        key = (ts.date(), label)
        sessions_by_day.setdefault(key, []).append((ts, row))

    days = sorted({k[0] for k in sessions_by_day})
    trades: list[tuple[str, float]] = []

    # For each day, look for setups using prior-day same-session pools
    for day_idx, day in enumerate(days[1:], 1):
        prev_day = days[day_idx - 1]

        # Use prior London H/L for the NY session
        for session in ("london", "ny", "asia"):
            today_bars = sessions_by_day.get((day, session), [])
            if len(today_bars) < FVG_LOOKBACK + 2:
                continue

            # Pool source: prior day's same session (London→London, NY→NY, Asia→Asia)
            pool_bars = sessions_by_day.get((prev_day, session), [])
            if not pool_bars:
                # Fall back to prior day's london if own session is empty
                pool_bars = sessions_by_day.get((prev_day, "london"), [])
            if not pool_bars:
                continue

            pool_hi, pool_lo = _session_hl(pool_bars)
            r = _find_setup(today_bars, pool_hi, pool_lo, mode, max_hold_bars)
            if r is not None:
                trades.append((str(day), r))
                break   # one trade per calendar day maximum

    return trades


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _seg(ts: list[tuple[str, float]]) -> dict:
    net = [r for _, r in ts]
    wins = sum(1 for r in net if r > 0)
    n = len(ts)
    return {
        "n": n,
        "win%": round(100 * wins / n, 1) if n else 0.0,
        "expR": round(sum(net) / n, 4) if net else 0.0,
        "totalR": round(sum(net), 1),
    }


def _buy_hold(df: pd.DataFrame, oos_start: str) -> float:
    oos = df.loc[df.index >= pd.Timestamp(oos_start), "Close"]
    if len(oos) < 2:
        return 0.0
    return round(100.0 * (float(oos.iloc[-1]) / float(oos.iloc[0]) - 1.0), 1)


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python tjr_futures.py <csv> <mode>")
        print("  mode: nq | es | nq_cfd | es_cfd")
        sys.exit(1)
    src, mode = sys.argv[1], sys.argv[2].lower()

    df = load_csv(src)
    ts = run(df, mode=mode)

    if len(ts) < 20:
        print(f"Only {len(ts)} setups — too few to judge. ({src})")
        return

    days = sorted({t[0] for t in ts})
    cut = days[int(len(days) * TRAIN_FRAC)]
    is_t  = [t for t in ts if t[0] <  cut]
    oos_t = [t for t in ts if t[0] >= cut]

    is_seg  = _seg(is_t)
    oos_seg = _seg(oos_t)
    bh = _buy_hold(df, cut)

    span = (df.index[-1] - df.index[0]).days

    print(f"\n=== TJR Futures (session-liquidity + FVG) | {src} | mode={mode} | "
          f"~{span}d / {span/365:.1f}y | 70/30 OOS ===")
    print(f"fee mode '{mode}': NQ≈1.75pt RT  ES≈0.50pt RT  CFD≈3bps RT")
    print(f"train < {cut}  |  OOS >= {cut}  |  OOS buy-hold {bh:+.1f}% (context)\n")
    print(f"{'segment':<9}{'setups':>8}{'win%':>8}{'net_expR':>10}{'net_totalR':>12}")
    print("-" * 47)
    for name, seg in (("IN-SAMP", is_seg), ("OOS", oos_seg)):
        print(f"{name:<9}{seg['n']:>8}{seg['win%']:>8}{seg['expR']:>10}{seg['totalR']:>12}")

    oos = oos_seg
    print("\n--- verdict ---")
    if oos["expR"] > 0:
        print(f"  OOS {oos['expR']:+.4f} R/trade > 0 after fees — UNUSUAL. Scrutinize hard.")
        print("  Check for look-ahead (pool levels computed from future bars?) before trusting.")
    else:
        print(f"  OOS {oos['expR']:+.4f} R/trade <= 0 after fees. No edge on this instrument/tf.")


if __name__ == "__main__":
    main()
