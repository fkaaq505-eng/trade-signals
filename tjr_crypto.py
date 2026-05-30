"""
TJR / "Path to Profitability" FVG-reversal model adapted for 24h crypto markets.

This is the GENUINE ICT model on the market it was designed for: Bitcoin/Ethereum
with real Asia / London / NY sessions as the liquidity pools, not the stock-ETF
proxy (PDH/PDL) used in tjr_bot.py.

ICT model mechanics (per UTC day, all three session windows):
  Sessions (UTC):
    Asia   00:00 – 08:00
    London 08:00 – 16:00  (strictly pre-NY overlap — ICT's "London killzone")
    NY     13:00 – 21:00  (NY open + overlap)

  Per-session liquidity raid → FVG reversal:
  1. Compute the PRIOR session's high and low (e.g., Asia H/L from yesterday's
     Asia session) — these are the "liquidity pools" retail stops cluster around.
  2. In the CURRENT session, watch for a RAID of those prior-session levels.
  3. After the raid, look for a 3-bar bearish/bullish FVG (same logic as tjr_bot):
       bearish FVG: bar[i-2].low > bar[i].high  (gap down — displacement)
       bullish FVG: bar[i-2].high < bar[i].low   (gap up — displacement)
  4. Entry at the FVG bar's close; stop past the raid extreme; target = opposite
     prior-session level.
  5. First valid setup per session only; hold until TP / SL / session end.

Why this beats PDH/PDL:
  - PDH/PDL only gives one pair of levels per day; session H/L gives 3 pairs,
    matching the actual intraday liquidity structure ICT tutorials describe.
  - The 3 sessions have distinct volatility profiles (Asia consolidates, London
    and NY break out), so filtering by session respects the model's intent.

Fees: 10 bps / side (0.10% taker) — realistic crypto round-turn.
OOS split: 70/30, older 70% in-sample, recent 30% held out. No look-ahead: session
levels are computed ONLY from bars prior to the current session bar.

Do NOT import or modify tjr_bot.py — this is a parallel file.

Usage:
    python tjr_crypto.py btc_5m.csv
    python tjr_crypto.py eth_5m.csv
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, time, timedelta

import pandas as pd

from data_csv import load_csv

FEE_BPS = 10.0       # per side (0.10% taker); round-turn = 20 bps
TRAIN = 0.70
MAX_R = 10.0         # cap absurd targets (sanity, not a tuned knob)

# Session windows in UTC hours [start, end) — INCLUSIVE start, EXCLUSIVE end
SESSIONS: dict[str, tuple[int, int]] = {
    "asia":   (0, 8),    # 00:00–08:00 UTC
    "london": (8, 16),   # 08:00–16:00 UTC
    "ny":     (13, 21),  # 13:00–21:00 UTC (overlaps London for NY open)
}


# ── session utilities ─────────────────────────────────────────────────────────

def _session_key(ts: pd.Timestamp) -> tuple[date, str]:
    """Return (utc_date, session_name) for a bar timestamp, or (date, None)."""
    h = ts.hour
    d = ts.date()
    # NY straddles the calendar boundary for Asia/Pacific if you shift, but here
    # we anchor to the UTC date on which the session bar falls.
    if 0 <= h < 8:
        return d, "asia"
    if 8 <= h < 16:
        return d, "london"
    if 13 <= h < 21:
        # London + NY overlap (13–16 UTC) is tagged as "ny" (NY takes precedence
        # for the liquidity model — this is the ICT "NY open killzone")
        return d, "ny"
    return d, "other"


def _prior_session(d: date, sess: str) -> tuple[date, str] | None:
    """Return the (date, session_name) that immediately precedes the given one."""
    order = ["asia", "london", "ny"]
    idx = order.index(sess)
    if idx > 0:
        return d, order[idx - 1]
    else:
        return d - timedelta(days=1), "ny"   # previous day's NY session


def _build_session_levels(df: pd.DataFrame) -> dict[tuple[date, str], tuple[float, float]]:
    """
    Returns {(date, session_name): (session_high, session_low)} for all sessions
    in the DataFrame. These are the completed session H/L used as liquidity pools.
    """
    levels: dict[tuple[date, str], tuple[float, float]] = defaultdict(lambda: (float("-inf"), float("inf")))
    hi_acc: dict[tuple[date, str], float] = defaultdict(lambda: float("-inf"))
    lo_acc: dict[tuple[date, str], float] = defaultdict(lambda: float("inf"))

    for ts, row in df.iterrows():
        key = _session_key(ts)
        if key[1] == "other":
            continue
        h, l = float(row["High"]), float(row["Low"])
        hi_acc[key] = max(hi_acc[key], h)
        lo_acc[key] = min(lo_acc[key], l)

    for key in hi_acc:
        levels[key] = (hi_acc[key], lo_acc[key])
    return dict(levels)


# ── per-session trade simulation ──────────────────────────────────────────────

def _simulate_session(bars: list[tuple[pd.Timestamp, pd.Series]],
                      prior_high: float, prior_low: float) -> float | None:
    """
    Simulate one session's worth of bars for a TJR raid→FVG setup.
    Returns net R after fees (already deducted), or None if no setup triggered.

    No look-ahead: session levels passed in were computed from bars BEFORE this
    session. Entry is at the FVG bar's close; outcome decided by subsequent bars.
    """
    round_turn = 2.0 * FEE_BPS / 10_000.0
    raided_high = raided_low = False
    raid_extreme = None
    raided_side = None
    win: list[tuple[float, float, float]] = []   # rolling 3-bar (hi, lo, cl)
    side = entry = stop = target = risk = None

    for _, b in bars:
        hi, lo, cl = float(b["High"]), float(b["Low"]), float(b["Close"])

        if side is None:
            # Detection phase
            win.append((hi, lo, cl))
            if len(win) > 3:
                win.pop(0)

            if raided_side is None:
                if hi > prior_high:
                    raided_side, raid_extreme = "high", hi
                elif lo < prior_low:
                    raided_side, raid_extreme = "low", lo
                continue

            # Update raid extreme (price may extend further)
            if raided_side == "high":
                raid_extreme = max(raid_extreme, hi)
            else:
                raid_extreme = min(raid_extreme, lo)

            if len(win) < 3:
                continue

            (h1, l1, _), _, (h3, l3, _) = win

            if raided_side == "high" and l1 > h3:       # bearish FVG → short
                side = "short"
                entry = cl
                stop = raid_extreme
                target = prior_low
                risk = stop - entry
            elif raided_side == "low" and h1 < l3:      # bullish FVG → long
                side = "long"
                entry = cl
                stop = raid_extreme
                target = prior_high
                risk = entry - stop

            if side is not None and (risk is None or risk <= 0):
                return None   # invalid geometry (e.g. entry past stop); skip

            continue

        # Simulation phase (bars after entry)
        fee_r = round_turn * entry / risk
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
    # Session ended, neither TP nor SL hit → session-flat
    last = float(bars[-1][1]["Close"])
    fee_r = round_turn * entry / risk
    gross = ((last - entry) if side == "long" else (entry - last)) / risk
    return max(min(gross, MAX_R), -1.0) - fee_r


# ── main run ──────────────────────────────────────────────────────────────────

def run(df: pd.DataFrame) -> list[tuple[str, str, float]]:
    """
    Run TJR crypto sessions model.
    Returns list of (date_str, session_name, net_r) for each triggered setup.
    """
    # Pre-compute all completed session H/L (no look-ahead: used only for prior session)
    session_levels = _build_session_levels(df)

    # Group bars by (date, session)
    session_bars: dict[tuple[date, str], list] = defaultdict(list)
    for ts, row in df.iterrows():
        key = _session_key(ts)
        if key[1] != "other":
            session_bars[key].append((ts, row))

    trades = []
    for key in sorted(session_bars.keys()):
        d, sess = key
        prior_key = _prior_session(d, sess)
        if prior_key not in session_levels:
            continue   # no prior session data yet
        prior_high, prior_low = session_levels[prior_key]
        if prior_high == float("-inf") or prior_low == float("inf"):
            continue   # degenerate prior session

        bars = session_bars[key]
        if len(bars) < 4:   # need enough bars to form FVG + simulate
            continue

        r = _simulate_session(bars, prior_high, prior_low)
        if r is not None:
            trades.append((str(d), sess, r))

    return trades


# ── reporting ─────────────────────────────────────────────────────────────────

def _seg(ts: list[tuple[str, str, float]]) -> dict:
    net = [r for _, _, r in ts]
    wins = sum(1 for r in net if r > 0)
    return {
        "n": len(ts),
        "win%": round(100 * wins / len(ts), 1) if ts else 0.0,
        "expR": round(sum(net) / len(net), 4) if net else 0.0,
        "totalR": round(sum(net), 1),
    }


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "btc_5m.csv"
    df = load_csv(src)
    ts = run(df)
    if len(ts) < 20:
        print(f"only {len(ts)} setups — too few to judge."); return

    days = sorted({t[0] for t in ts})
    cut = days[int(len(days) * TRAIN)]
    is_t = [t for t in ts if t[0] < cut]
    oos_t = [t for t in ts if t[0] >= cut]

    # OOS buy-hold
    oos_df = df[df.index >= cut]
    bh = (100.0 * (float(oos_df["Close"].iloc[-1]) / float(oos_df["Close"].iloc[0]) - 1.0)
          if len(oos_df) > 1 else 0.0)

    print(f"\n=== TJR CRYPTO (real Asia/London/NY sessions) — {src} ===")
    print(f"Fee: {FEE_BPS} bps/side ({2*FEE_BPS} bps round-turn) | EOD-flat per session")
    print(f"train < {cut} | OOS >= {cut}")
    print(f"OOS buy-hold {bh:+.1f}% (context only)\n")
    print(f"{'segment':<9}{'setups':>8}{'win%':>8}{'net_expR':>10}{'net_totalR':>12}")
    print("-" * 47)
    for name, seg in (("IN-SAMP", _seg(is_t)), ("OOS", _seg(oos_t))):
        print(f"{name:<9}{seg['n']:>8}{seg['win%']:>8}{seg['expR']:>10}{seg['totalR']:>12}")

    # Per-session breakdown
    print(f"\n--- OOS breakdown by session ---")
    print(f"{'session':<10}{'setups':>8}{'win%':>8}{'net_expR':>10}{'net_totalR':>12}")
    print("-" * 48)
    for sess in ("asia", "london", "ny"):
        sub = [(d, s, r) for d, s, r in oos_t if s == sess]
        if sub:
            g = _seg(sub)
            print(f"{sess:<10}{g['n']:>8}{g['win%']:>8}{g['expR']:>10}{g['totalR']:>12}")
        else:
            print(f"{sess:<10}{'0':>8}")

    oos = _seg(oos_t)
    print("\n--- verdict ---")
    if oos["expR"] > 0:
        print(f"  OOS net {oos['expR']:+.4f} R/trade > 0 — EXTRAORDINARY. Scrutinize for look-ahead")
        print("  bugs in _build_session_levels / _prior_session before trusting any number here.")
    else:
        print(f"  OOS net {oos['expR']:+.4f} R/trade <= 0 after {FEE_BPS} bps/side taker fees.")
        print("  TJR's FVG-reversal model on REAL crypto sessions has NO validated edge.")
        print("  Same conclusion as every prior SPY/QQQ model in this repo.")


if __name__ == "__main__":
    main()
