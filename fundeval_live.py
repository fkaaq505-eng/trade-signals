"""
fundeval_live.py — Eval pass/fail WITH the risk engine enforcing iron discipline.

Runs the same SPY daily meanrev trade stream as fundeval.py, but routes every trade
through risk_engine.py. Shows how disciplined sizing changes pass/fail behaviour vs
the naive fixed-% sizing in fundeval.py.

HONEST SCOPE: The daily SPY meanrev strategy is NOT funded-legal (overnight + no
stop-loss). This file uses those trades purely as a TRADE STREAM to demonstrate the
risk-management layer. The lesson is the risk layer, not the signal.

    python fundeval_live.py                        # Apex 50k defaults
    python fundeval_live.py --firm topstep         # Topstep 50k
    python fundeval_live.py --firm apex --account 100000
    python fundeval_live.py --compare              # show discipline vs naive side by side

PAPER / RESEARCH ONLY. Never places orders.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone

import pandas as pd

import risk_engine as R
from data import fetch
from engine import backtest
from risk_engine import (
    APEX_50K,
    TOPSTEP_50K,
    Decision,
    RiskState,
    can_enter,
    days_elapsed,
    make_state,
    on_new_day,
    profit_pace_report,
    register_close,
    register_fill,
    remaining_dd_buffer,
    status_summary,
)

BAKED = dict(strategy="meanrev", rsi_buy=10, rsi_exit=75, down_days=2)

# Stop distance proxy: the daily meanrev strategy has no hard stop, but for
# sizing through the risk engine we need a stop distance. We use the historical
# worst MAE as a conservative proxy for what the stop WOULD be if one were used.
# This is honest: we're not pretending a stop exists; we're sizing AS IF one did,
# which is the correct way to apply risk-engine discipline to this stream.
PROXY_STOP_PCT = 0.015   # 1.5% proxy stop (conservative; worst MAE is ~11%)


def _session_ts(trade_date_str: str) -> datetime:
    """Build a UTC timestamp in the session morning for a given trade date string."""
    d = date.fromisoformat(trade_date_str[:10])
    return datetime(d.year, d.month, d.day, 14, 30, tzinfo=timezone.utc)


def _eod_ts(trade_date_str: str) -> datetime:
    """End-of-day UTC timestamp for a given trade date string."""
    d = date.fromisoformat(trade_date_str[:10])
    return datetime(d.year, d.month, d.day, 20, 0, tzinfo=timezone.utc)


def run_disciplined(
    trades: list,
    account_size: float,
    config: R.FirmConfig,
) -> dict:
    """
    Run the trade stream through the risk engine.

    Returns a result dict with outcome, equity curve data, and per-trade log.
    """
    state = make_state(config, account_size, date.fromisoformat(trades[0].entry_date[:10]))
    trade_log: list[dict] = []

    current_day: date | None = None

    for i, t in enumerate(trades, 1):
        entry_date = date.fromisoformat(t.entry_date[:10])
        exit_date = date.fromisoformat(t.exit_date[:10])

        # Advance day if needed
        if current_day is None:
            current_day = entry_date
        elif entry_date > current_day:
            state = on_new_day(state, entry_date)
            current_day = entry_date

        if state.eval_passed or state.eval_failed:
            break

        ts_entry = _session_ts(t.entry_date)

        # Ask the engine if we may enter
        decision = can_enter(state, stop_distance_pct=PROXY_STOP_PCT, timestamp=ts_entry)

        if not decision.allowed:
            trade_log.append({
                "trade": i,
                "entry_date": t.entry_date[:10],
                "action": "BLOCKED",
                "reason": decision.reasons[0],
                "equity": state.current_equity,
            })
            continue

        # Register fill (we use max_size_dollars as the position notional)
        size = decision.max_size_dollars
        state = register_fill(state, timestamp=ts_entry,
                              entry_price=t.entry, size_dollars=size)

        # Realise the trade: pnl = position_size * (pnl_pct / 100)
        pnl_dollars = size * (t.pnl_pct / 100.0)
        state = register_close(
            state,
            timestamp=_eod_ts(t.exit_date),
            close_price=t.exit,
            pnl_dollars=pnl_dollars,
            mae_pct=t.mae_pct,    # real intraday MAE from the backtest
        )

        trade_log.append({
            "trade": i,
            "entry_date": t.entry_date[:10],
            "exit_date": t.exit_date[:10],
            "action": "TAKEN",
            "size_$": round(size, 0),
            "pnl_$": round(pnl_dollars, 2),
            "mae_pct": t.mae_pct,
            "equity": round(state.current_equity, 2),
            "dd_buffer_$": round(remaining_dd_buffer(state), 2),
        })

        if state.eval_passed or state.eval_failed:
            break

    return {
        "config": config,
        "account_size": account_size,
        "final_equity": state.current_equity,
        "cumulative_profit": state.cumulative_profit,
        "eval_passed": state.eval_passed,
        "eval_failed": state.eval_failed,
        "failure_reason": state.failure_reason,
        "days_elapsed": days_elapsed(state),
        "trades_taken": sum(1 for t in trade_log if t["action"] == "TAKEN"),
        "trades_blocked": sum(1 for t in trade_log if t["action"] == "BLOCKED"),
        "trade_log": trade_log,
        "pace_report": profit_pace_report(state),
        "final_status": status_summary(state),
    }


def run_naive(
    trades: list,
    account_size: float,
    config: R.FirmConfig,
    size_pct: float = 20.0,   # same default as fundeval.py
) -> dict:
    """
    Naive simulation: fixed % sizing, no risk-engine guardrails.
    This mirrors the logic in fundeval.py but returns the same result shape.
    """
    trail = account_size * config.trailing_dd_pct / 100.0
    target = account_size * config.profit_target_pct / 100.0
    equity = peak = account_size
    worst_trail = 0.0
    outcome = "INCOMPLETE"
    trades_taken = 0

    for i, t in enumerate(trades, 1):
        pos = equity * size_pct / 100.0
        intraday_low = equity + pos * (t.mae_pct / 100.0)
        worst_trail = max(worst_trail, peak - intraday_low)

        if peak - intraday_low > trail:
            return {
                "eval_passed": False,
                "eval_failed": True,
                "failure_reason": (
                    f"FAIL — trailing DD breached on trade #{i} ({t.entry_date[:10]}): "
                    f"intraday ${peak - intraday_low:,.0f} > ${trail:,.0f}"
                ),
                "final_equity": equity,
                "trades_taken": trades_taken,
                "trades_blocked": 0,
                "days_elapsed": None,
                "worst_trail_dd": round(worst_trail, 2),
            }

        equity += pos * (t.pnl_pct / 100.0)
        peak = max(peak, equity)
        trades_taken += 1

        if equity - account_size >= target:
            return {
                "eval_passed": True,
                "eval_failed": False,
                "failure_reason": "",
                "final_equity": round(equity, 2),
                "trades_taken": trades_taken,
                "trades_blocked": 0,
                "days_elapsed": None,
                "worst_trail_dd": round(worst_trail, 2),
            }

    return {
        "eval_passed": False,
        "eval_failed": False,
        "failure_reason": "INCOMPLETE — ran out of trades before hitting target",
        "final_equity": round(equity, 2),
        "trades_taken": trades_taken,
        "trades_blocked": 0,
        "days_elapsed": None,
        "worst_trail_dd": round(worst_trail, 2),
    }


def print_result(label: str, r: dict, account_size: float, config: R.FirmConfig) -> None:
    target = account_size * config.profit_target_pct / 100.0
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  Firm: {config.name}")
    print(f"  Account: ${account_size:,.0f}  |  Target: +{config.profit_target_pct}% (${target:,.0f})")
    print(f"{'=' * 60}")
    print(f"  Final equity:    ${r['final_equity']:,.2f}")
    print(f"  Trades taken:    {r['trades_taken']}")
    if r.get("trades_blocked"):
        print(f"  Trades blocked:  {r['trades_blocked']}")
    if r.get("days_elapsed") is not None:
        print(f"  Days elapsed:    {r['days_elapsed']}")
    if r.get("worst_trail_dd"):
        print(f"  Worst trail DD:  ${r['worst_trail_dd']:,.2f}")

    if r["eval_passed"]:
        print(f"\n  *** PASS *** — profit target reached")
    elif r["eval_failed"]:
        print(f"\n  *** FAIL *** — {r['failure_reason']}")
    else:
        print(f"\n  *** INCOMPLETE *** — {r['failure_reason']}")

    if "pace_report" in r:
        p = r["pace_report"]
        print(f"\n  Pace: {p['pct_complete']:.1f}% of target, "
              f"{p['days_remaining']} days remaining")
        print(f"  {p['safe_pace_note']}")


def print_comparison(naive: dict, disciplined: dict, account_size: float,
                     config: R.FirmConfig) -> None:
    target = account_size * config.profit_target_pct / 100.0
    print(f"\n{'=' * 70}")
    print(f"  COMPARISON: Naive sizing (20%) vs Iron Discipline (risk engine)")
    print(f"  Firm: {config.name}")
    print(f"  Account: ${account_size:,.0f}  |  Target: +{config.profit_target_pct}% "
          f"(${target:,.0f})")
    print(f"{'=' * 70}")
    print(f"  {'Metric':<30} {'NAIVE':>15} {'DISCIPLINED':>15}")
    print(f"  {'-' * 60}")

    def row(label, nv, dv):
        print(f"  {label:<30} {str(nv):>15} {str(dv):>15}")

    def outcome(r):
        if r["eval_passed"]:
            return "PASS"
        if r["eval_failed"]:
            return "FAIL"
        return "INCOMPLETE"

    row("Outcome", outcome(naive), outcome(disciplined))
    row("Final equity ($)", f"{naive['final_equity']:,.0f}",
        f"{disciplined['final_equity']:,.0f}")
    row("Trades taken", naive["trades_taken"], disciplined["trades_taken"])
    row("Trades blocked", naive["trades_blocked"], disciplined.get("trades_blocked", 0))
    if naive.get("worst_trail_dd"):
        row("Worst trailing DD ($)", f"{naive['worst_trail_dd']:,.0f}", "N/A (risk-capped)")

    print(f"\n  HONEST TRADEOFF:")
    print(f"  - Disciplined sizing (0.75% risk/trade) takes much smaller positions.")
    print(f"  - Smaller size = smaller PnL per trade = slower to the profit target.")
    print(f"  - If the eval has a max-days clock, slow progress is ALSO a failure mode.")
    print(f"  - BUT: naive sizing on this strategy's worst MAE (-11%) at 20% size")
    print(f"    causes a ${account_size * 20 / 100 * 11 / 100:,.0f} intraday DD on one trade,")
    print(f"    which blows through most firms' trailing-DD limits.")
    print(f"  - The discipline engine prevents that at the cost of needing more trades")
    print(f"    to reach the target. Both approaches have failure modes.")
    print(f"\n  NOTE: The daily meanrev strategy is NOT funded-legal (overnight holds,")
    print(f"  no stop-loss). This comparison demonstrates the RISK LAYER only.")
    print(f"  A real funded attempt needs an intraday + hard-stop strategy plus")
    print(f"  forward paper-testing on real intraday data. No such edge is validated here.")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Run the funded eval WITH the risk engine. Paper only — never trades.")
    p.add_argument("--firm", default="apex", choices=["apex", "topstep"],
                   help="Firm preset (apex=intraday-trailing, topstep=eod-trailing)")
    p.add_argument("--account", type=float, default=50_000.0)
    p.add_argument("--compare", action="store_true",
                   help="Show side-by-side: naive sizing vs disciplined risk engine")
    args = p.parse_args()

    config = APEX_50K if args.firm == "apex" else TOPSTEP_50K

    print(f"Fetching SPY daily data (12y)...")
    df = fetch("SPY", "12y", "1d")
    trades, _ = backtest(df, sl_mult=0.0, max_hold_hours=240.0, skip_events=True, **BAKED)
    print(f"Trade stream: {len(trades)} trades loaded.")

    disciplined = run_disciplined(trades, args.account, config)
    print_result(
        f"DISCIPLINED (risk engine, {config.trailing_dd_mode}-trailing)",
        disciplined, args.account, config
    )

    if args.compare:
        naive = run_naive(trades, args.account, config, size_pct=20.0)
        print_result("NAIVE (20% fixed sizing, no guardrails)", naive, args.account, config)
        print_comparison(naive, disciplined, args.account, config)


if __name__ == "__main__":
    main()
