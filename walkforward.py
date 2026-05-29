"""
Walk-forward validation for the SPY Connors RSI(2) mean-reversion strategy.

The honest question this answers: is the baked 82.4% win rate real, or did we
curve-fit it on 12 years we also tuned on? Two out-of-sample tests:

  Mode A (fixed)      — the baked config applied year-by-year on the recent
                        held-out years. Shows whether the win rate is broad or
                        concentrated in the older, tuning-heavy period.
  Mode B (reoptimize) — the only TRUE walk-forward: for each test year, re-tune
                        params on PRIOR data only (sweep grid), then trade that
                        year with the chosen params. The test year never sees
                        its own data during tuning. This is what exposes overfit.

Out-of-sample trades from every fold are concatenated and scored as ONE stream.
We report win / net / drawdown and ALWAYS show buy_hold next to it — a high win
rate is not the same as more money.

Indicator warmup is handled by feeding the engine all bars up to the test-year
end, then counting only trades ENTERED inside the test year. Signals are causal
(rolling/ewm use past+current only), so future bars never change a past signal.

    python walkforward.py            # SPY
    python walkforward.py QQQ

NEVER connects to a broker. NEVER places orders. Simulation only.
"""

from __future__ import annotations

import sys
from math import inf

import pandas as pd

from data import fetch
from engine import Trade, backtest, stats

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "SPY"
PERIOD, INTERVAL = "12y", "1d"
MIN_TRAIN_YEARS = 5         # initial anchored train before the first OOS year
MIN_TRADES_GATE = 20        # never trust an optimized config from too few trades
FEE_BPS = 1.0
EXIT_BUFFER_DAYS = 45       # let a year-end OOS trade exit on its real signal

# Current champion (baked defaults — see strategy.py / HANDOFF).
BAKED = dict(strategy="meanrev", rsi_buy=10.0, rsi_exit=75.0, down_days=2)

# Mode-B tuning grid: mirrors sweep.py (rsi_buy/rsi_exit) plus the down_days
# choice that the baked config also tuned. event-filter stays on (a risk policy,
# not a fitted parameter) to keep the grid honest and small.
GRID = [
    dict(strategy="meanrev", rsi_buy=rb, rsi_exit=rx, down_days=dd)
    for rb in (5, 10, 15)
    for rx in (65, 75)
    for dd in (0, 2, 3)
]


def run(df: pd.DataFrame, params: dict) -> tuple[list[Trade], pd.Series]:
    """Backtest with the shared mean-reversion settings (no stop, long hold)."""
    return backtest(df, sl_mult=0.0, max_hold_hours=240.0, skip_events=True,
                    fee_bps=FEE_BPS, **params)


def equity_from_trades(trades: list[Trade]) -> pd.Series:
    """Rebuild the compounding equity curve from a trade list, fees included.

    Matches the engine: equity *= (exit/entry) * (1 - round_turn) per trade.
    pnl_pct is the gross move, so (1 + pnl_pct/100) reconstructs (exit/entry).
    """
    round_turn = 2.0 * FEE_BPS / 10_000.0
    equity, curve = 1.0, []
    for t in trades:
        equity *= (1.0 + t.pnl_pct / 100.0) * (1.0 - round_turn)
        curve.append(equity)
    return pd.Series(curve or [1.0])


def year_close(df: pd.DataFrame, year: int) -> pd.Series:
    return df.loc[df.index.year == year, "Close"]


def oos_trades_for_year(df: pd.DataFrame, params: dict, year: int) -> list[Trade]:
    """Trades ENTERED inside `year`, simulated with full prior history for warmup."""
    y_start = pd.Timestamp(year=year, month=1, day=1)
    y_end = pd.Timestamp(year=year, month=12, day=31)
    feed = df.loc[df.index <= y_end + pd.Timedelta(days=EXIT_BUFFER_DAYS)]
    trades, _ = run(feed, params)
    return [t for t in trades
            if y_start <= pd.Timestamp(t.entry_date) <= y_end]


def optimize(train_df: pd.DataFrame) -> tuple[dict, dict | None]:
    """Pick the best grid config on TRAIN only (win% then net%, min-trades gate).

    Returns (params, in_sample_stats). Falls back to baked defaults if no config
    clears the trade gate (train window too short to trust an optimization).
    """
    buy_hold = train_df["Close"] / train_df["Close"].iloc[0]
    scored = []
    for params in GRID:
        trades, eq = run(train_df, params)
        s = stats(trades, eq, buy_hold)
        if s.get("trades", 0) >= MIN_TRADES_GATE:
            scored.append((params, s))
    if not scored:
        return dict(BAKED), None
    best = max(scored, key=lambda ps: (ps[1]["win_rate_%"],
                                       ps[1]["net_return_%(after fees)"]))
    return best[0], best[1]


def walk(df: pd.DataFrame, oos_years: list[int], reoptimize: bool):
    """Run one mode across all OOS years. Returns (per-year rows, all OOS trades)."""
    rows, all_oos = [], []
    for year in oos_years:
        train = df.loc[df.index < pd.Timestamp(year=year, month=1, day=1)]
        params, is_stats = optimize(train) if reoptimize else (dict(BAKED), None)
        oos = oos_trades_for_year(df, params, year)
        s = stats(oos, equity_from_trades(oos), year_close(df, year))
        rows.append((year, params, is_stats, s))
        all_oos.extend(oos)
    return rows, all_oos


def combined(df: pd.DataFrame, oos_years: list[int], all_oos: list[Trade]) -> dict:
    """Score every OOS trade as one chronological compounding stream."""
    start = pd.Timestamp(year=oos_years[0], month=1, day=1)
    span_close = df.loc[df.index >= start, "Close"]
    return stats(all_oos, equity_from_trades(all_oos), span_close)


# --- printing ---------------------------------------------------------------

def _cfg(params: dict) -> str:
    return f"{int(params['rsi_buy'])}/{int(params['rsi_exit'])}/{params['down_days']}"


def print_fixed_table(rows) -> None:
    print(f"\n--- Mode A: baked config {_cfg(BAKED)} held fixed, year-by-year OOS ---")
    print(f"{'year':>6}{'trades':>8}{'win%':>7}{'PF':>7}{'net%':>8}{'maxDD%':>8}{'buyhold%':>10}")
    print("-" * 54)
    for year, _params, _is, s in rows:
        if s.get("trades", 0) == 0:
            print(f"{year:>6}{'(no trades)':>8}")
            continue
        print(f"{year:>6}{s['trades']:>8}{s['win_rate_%']:>7}{s['profit_factor']:>7}"
              f"{s['net_return_%(after fees)']:>8}{s['max_drawdown_%']:>8}"
              f"{s['buy_hold_return_%']:>10}")


def print_reopt_table(rows) -> None:
    print(f"\n--- Mode B: re-tuned each year on PRIOR data only (true walk-forward) ---")
    print(f"  cfg = rsi_buy/rsi_exit/down_days chosen from that year's training history")
    print(f"{'year':>6}{'cfg':>9}{'IS_win%':>9}{'trades':>8}{'win%':>7}{'net%':>8}{'maxDD%':>8}{'buyhold%':>10}")
    print("-" * 65)
    for year, params, is_stats, s in rows:
        is_win = is_stats["win_rate_%"] if is_stats else "baked"
        if s.get("trades", 0) == 0:
            print(f"{year:>6}{_cfg(params):>9}{str(is_win):>9}{'(no trades)':>8}")
            continue
        print(f"{year:>6}{_cfg(params):>9}{str(is_win):>9}{s['trades']:>8}"
              f"{s['win_rate_%']:>7}{s['net_return_%(after fees)']:>8}"
              f"{s['max_drawdown_%']:>8}{s['buy_hold_return_%']:>10}")


def print_combined(label: str, s: dict) -> None:
    if s.get("trades", 0) == 0:
        print(f"\n{label}: no out-of-sample trades.")
        return
    print(f"\n{label}: {s['trades']} trades | {s['win_rate_%']}% win | "
          f"PF {s['profit_factor']} | net {s['net_return_%(after fees)']}% | "
          f"DD {s['max_drawdown_%']}% | buy&hold {s['buy_hold_return_%']}%")


def verdict(oos: dict, is_ref: dict) -> str:
    if oos.get("trades", 0) == 0:
        return "  INCONCLUSIVE: no out-of-sample trades to judge."

    win, pf = oos["win_rate_%"], oos["profit_factor"]
    net, ddp, bh = (oos["net_return_%(after fees)"], oos["max_drawdown_%"],
                    oos["buy_hold_return_%"])
    gap = win - is_ref["win_rate_%"]
    pf_ok = pf == inf or pf >= 1.5
    pf_bad = pf != inf and pf < 1.2

    if gap >= -5.0 and pf_ok and net > 0:
        head = ("HOLDS UP — out-of-sample win rate is within 5 pts of the "
                f"in-sample {is_ref['win_rate_%']}% and stays profitable. "
                "Not materially overfit.")
    elif gap <= -10.0 or pf_bad or net <= 0:
        head = ("OVERFIT WARNING — out-of-sample drops sharply from in-sample "
                f"{is_ref['win_rate_%']}%. The headline 82% does NOT hold "
                "honestly out of sample.")
    else:
        head = ("PARTIAL — out-of-sample is weaker than in-sample but still "
                "positive. Treat 82% as optimistic; expect less live.")

    money = (f"Money check: OOS net {net}% vs buy&hold {bh}% over the same "
             f"window. A high win rate is NOT more money — the real edge is the "
             f"shallow drawdown ({ddp}%), i.e. a smoother ride, not a bigger one.")
    return f"  {head}\n  {money}"


def main() -> None:
    df = fetch(SYMBOL, PERIOD, INTERVAL)
    years = sorted(set(df.index.year))
    if len(years) < MIN_TRAIN_YEARS + 2:
        raise SystemExit(f"Need >= {MIN_TRAIN_YEARS + 2} years of data; got {len(years)}.")
    oos_years = years[MIN_TRAIN_YEARS:]

    # In-sample reference: baked config on the FULL sample (the 82% claim).
    full_trades, full_eq = run(df, BAKED)
    is_ref = stats(full_trades, full_eq, df["Close"] / df["Close"].iloc[0])

    print(f"\n=== WALK-FORWARD VALIDATION: {SYMBOL} ({PERIOD} {INTERVAL}) ===")
    print(f"in-sample baked full run: {is_ref['win_rate_%']}% win | "
          f"net {is_ref['net_return_%(after fees)']}% | "
          f"DD {is_ref['max_drawdown_%']}% | {is_ref['trades']} trades | "
          f"buy&hold {is_ref['buy_hold_return_%']}%")
    print(f"train >= {years[0]}..{oos_years[0] - 1}  |  held-out OOS years: "
          f"{oos_years[0]}..{oos_years[-1]}")

    fixed_rows, fixed_oos = walk(df, oos_years, reoptimize=False)
    print_fixed_table(fixed_rows)
    fixed_combined = combined(df, oos_years, fixed_oos)
    print_combined("COMBINED OOS (fixed baked params)", fixed_combined)

    reopt_rows, reopt_oos = walk(df, oos_years, reoptimize=True)
    print_reopt_table(reopt_rows)
    reopt_combined = combined(df, oos_years, reopt_oos)
    print_combined("COMBINED OOS (re-optimized)", reopt_combined)

    print("\n=== VERDICT ===")
    print("Mode A (does the baked 82% config hold on recent held-out years?):")
    print(verdict(fixed_combined, is_ref))
    print("Mode B (does the TUNING PROCESS overfit?):")
    print(verdict(reopt_combined, is_ref))


if __name__ == "__main__":
    main()
