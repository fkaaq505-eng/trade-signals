"""
FUNDED FORWARD-TEST — the "best strategy to pass" made operational (paper only).

There is no validated entry edge on free data (HANDOFF 7-19). The honest "thing that
passes a funded eval" is IRON RISK DISCIPLINE on the best-barrier firm, plus cheap-reset
attempts (see FUNDED_EVAL.md, eval_montecarlo.py). This module is that discipline made
into a live, persistent paper guardrail + tracker:

  - It SIZES every trade to the firm's drawdown buffer (risk_engine), enforces the
    daily-loss lockout, max-trades/day, and mandatory EOD-flat.
  - It TRACKS your progress through one evaluation attempt (equity, trailing buffer,
    days, distance to target, consistency) and tells you PASS / FAIL the moment a rule
    triggers.
  - It LOGS every closed paper trade to journal.csv (strat=funded) so journal.py gives
    you the real win%/expectancy/PF track record BEFORE you ever risk a real eval fee.

It NEVER places an order and never invents a signal — YOU bring the entries (discretionary
or otherwise); this enforces the risk math that actually decides pass/fail. State persists
in funded_state.json (gitignored, private).

    python funded_forward.py plan                         # today's disciplined plan
    python funded_forward.py fill --entry 20000 --stop 19960   # open (size auto-capped)
    python funded_forward.py close --exit 20030          # close + log to journal
    python funded_forward.py status                      # full snapshot
    python funded_forward.py reset --firm apex_eod       # start a fresh attempt
    python funded_forward.py --help

Pick the firm with FUNDED_EVAL.md / `python eval_montecarlo.py`. Default = Apex 4.0 EOD
(cheap promo resets → best cumulative odds). Sizing is conservative; verify firm rules live.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone

import journal
from risk_engine import (
    APEX_50K, TOPSTEP_50K, DayStats, FirmConfig, RiskState,
    can_enter, days_remaining, must_flatten, on_new_day,
    profit_pace_report, register_close, register_fill, status_summary,
)

STATE_FILE = "funded_state.json"
JOURNAL_FILE = "journal.csv"
NO_DAILY_LIMIT = 100.0   # sentinel: firms with no daily-loss rule (engine needs a number)

# --- Firm configs matching FUNDED_EVAL.md (50k). VERIFY on the live rulebook. ----------
# Modelled with risk_engine's eod/intraday trailing. "EOD-lock" firms are modelled as
# "eod" (the engine's eod-trailing is a safe, slightly-stricter proxy for lock-then-freeze).
APEX_EOD = FirmConfig(
    name="Apex 4.0 EOD 50k (lock@+$100, 30-day cap) — VERIFY",
    trailing_dd_pct=4.0, daily_loss_limit_pct=2.0, profit_target_pct=6.0,
    max_eval_days=30, trailing_dd_mode="eod", session_close=(21, 0),
    eod_flat_mandatory=True, consistency_ratio_limit=0.0,
    per_trade_risk_pct=1.0, max_trades_per_day=3,
)
ALPHA_ZERO = FirmConfig(
    name="Alpha Futures Zero 50k (EOD-lock@start, no consistency) — VERIFY",
    trailing_dd_pct=4.0, daily_loss_limit_pct=2.0, profit_target_pct=6.0,
    max_eval_days=200, trailing_dd_mode="eod", session_close=(21, 0),
    eod_flat_mandatory=True, consistency_ratio_limit=0.0,
    per_trade_risk_pct=1.0, max_trades_per_day=3,
)
BULENOX = FirmConfig(
    name="Bulenox 50k Opt.1 (intraday, big $2.5k buffer) — VERIFY",
    trailing_dd_pct=5.0, daily_loss_limit_pct=NO_DAILY_LIMIT, profit_target_pct=6.0,
    max_eval_days=200, trailing_dd_mode="intraday", session_close=(21, 0),
    eod_flat_mandatory=True, consistency_ratio_limit=0.0,
    per_trade_risk_pct=1.0, max_trades_per_day=3,
)
FIRMS: dict[str, FirmConfig] = {
    "apex_eod": APEX_EOD, "alpha_zero": ALPHA_ZERO, "bulenox": BULENOX,
    "apex": APEX_50K, "topstep": TOPSTEP_50K,
}
DEFAULT_FIRM = "apex_eod"
_BY_NAME = {f.name: k for k, f in FIRMS.items()}


# ---------------------------------------------------------------------------
# Persistence (RiskState <-> JSON of primitives)
# ---------------------------------------------------------------------------
def state_to_dict(s: RiskState) -> dict:
    return {
        "firm_key": _BY_NAME.get(s.config.name, DEFAULT_FIRM),
        "account_size": s.account_size,
        "current_equity": s.current_equity,
        "equity_peak": s.equity_peak,
        "start_date": s.start_date.isoformat(),
        "current_date": s.current_date.isoformat(),
        "cumulative_profit": s.cumulative_profit,
        "today": {"trade_date": s.today_stats.trade_date.isoformat(),
                  "realized_pnl": s.today_stats.realized_pnl,
                  "trade_count": s.today_stats.trade_count},
        "daily_profit_history": [[d.isoformat(), p] for d, p in s.daily_profit_history],
        "daily_locked_out": s.daily_locked_out,
        "eval_passed": s.eval_passed, "eval_failed": s.eval_failed,
        "failure_reason": s.failure_reason,
        "in_position": s.in_position, "position_entry_price": s.position_entry_price,
        "position_size": s.position_size,
        "position_entry_ts": s.position_entry_ts.isoformat() if s.position_entry_ts else None,
    }


def state_from_dict(d: dict) -> RiskState:
    cfg = FIRMS.get(d["firm_key"], FIRMS[DEFAULT_FIRM])
    ts = d.get("position_entry_ts")
    return RiskState(
        config=cfg, account_size=d["account_size"], current_equity=d["current_equity"],
        equity_peak=d["equity_peak"], start_date=date.fromisoformat(d["start_date"]),
        current_date=date.fromisoformat(d["current_date"]),
        cumulative_profit=d["cumulative_profit"],
        today_stats=DayStats(date.fromisoformat(d["today"]["trade_date"]),
                             d["today"]["realized_pnl"], d["today"]["trade_count"]),
        daily_profit_history=tuple((date.fromisoformat(x), p)
                                   for x, p in d["daily_profit_history"]),
        daily_locked_out=d["daily_locked_out"], eval_passed=d["eval_passed"],
        eval_failed=d["eval_failed"], failure_reason=d["failure_reason"],
        in_position=d["in_position"], position_entry_price=d["position_entry_price"],
        position_size=d["position_size"],
        position_entry_ts=datetime.fromisoformat(ts) if ts else None,
    )


def load_state(path: str, firm_key: str, account: float) -> RiskState:
    if os.path.exists(path):
        with open(path) as f:
            return state_from_dict(json.load(f))
    cfg = FIRMS[firm_key]
    today = date.today()
    return RiskState(
        config=cfg, account_size=account, current_equity=account, equity_peak=account,
        start_date=today, current_date=today, cumulative_profit=0.0,
        today_stats=DayStats(today, 0.0, 0), daily_profit_history=(),
        daily_locked_out=False, eval_passed=False, eval_failed=False, failure_reason="",
        in_position=False, position_entry_price=0.0, position_size=0.0,
        position_entry_ts=None,
    )


def save_state(path: str, s: RiskState) -> None:
    with open(path, "w") as f:
        json.dump(state_to_dict(s), f, indent=2)


def _now(args) -> datetime:
    return (datetime.fromisoformat(args.now) if getattr(args, "now", None)
            else datetime.now(timezone.utc))


def _roll_day(state: RiskState, now: datetime) -> RiskState:
    """Advance the engine to today if the calendar date changed (resets daily lockout)."""
    if now.date() != state.current_date:
        return on_new_day(state, now.date())
    return state


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_plan(state: RiskState, args) -> RiskState:
    now = _now(args)
    state = _roll_day(state, now)
    s = status_summary(state)
    pace = profit_pace_report(state)
    print(f"\n=== FUNDED PAPER PLAN — {s['firm']} ===")
    print(f"  paper only · no proven edge · discipline track-record builder\n")
    if s["eval_passed"]:
        print(f"  ✅ EVAL PASSED — equity ${s['current_equity']:,.0f}. Stop; bank it.")
        return state
    if s["eval_failed"]:
        print(f"  ❌ EVAL FAILED — {s['failure_reason']}\n  reset for a fresh attempt: "
              f"python funded_forward.py reset --firm <firm>")
        return state
    print(f"  equity            ${s['current_equity']:,.0f}  (peak ${s['equity_peak']:,.0f})")
    print(f"  to TARGET          ${s['profit_target'] - s['cumulative_profit']:,.0f} "
          f"left (target +${s['profit_target']:,.0f})")
    print(f"  trailing-DD buffer ${s['trailing_dd_buffer_remaining']:,.0f}  "
          f"(limit ${s['trailing_dd_limit']:,.0f}, mode {s['trailing_dd_mode']})")
    print(f"  today              PnL ${s['today_pnl']:,.0f} · "
          f"{s['today_trades']}/{s['max_trades_per_day']} trades · "
          f"daily-loss limit ${s['daily_loss_limit']:,.0f}"
          f"{'  ⛔ LOCKED OUT' if s['daily_locked_out'] else ''}")
    print(f"  days               {s['days_elapsed']} elapsed · {s['days_remaining']} left")
    print(f"  pace               {pace.get('pct_complete', 0):.0f}% to target · "
          f"{pace.get('safe_pace_note', '')}")
    # Show the max size the rules permit for a sample stop distance.
    if must_flatten(state, now):
        print("\n  ⛔ EOD-FLAT ZONE — flatten everything, NO new entries.")
    elif not state.in_position:
        for stop_pct in (0.001, 0.0025, 0.005):
            d = can_enter(state, stop_pct, now)
            tag = (f"max size ${d.max_size_dollars:,.0f}" if d.allowed
                   else f"BLOCKED: {d.reasons[0]}")
            print(f"  if stop {stop_pct*100:.2f}% away -> {tag}")
            if not d.allowed:
                break
    else:
        print(f"\n  IN POSITION since {state.position_entry_ts} @ "
              f"${state.position_entry_price:,.2f} (${state.position_size:,.0f} notional). "
              f"Manage to stop/target; flatten by EOD.")
    print("\n  RULE: size to the buffer, honour the daily lockout, flat by close. "
          "Discipline is the edge.")
    return state


def cmd_fill(state: RiskState, args) -> RiskState:
    now = _now(args)
    state = _roll_day(state, now)
    if args.entry <= 0 or args.stop <= 0:
        raise SystemExit("--entry and --stop must be > 0")
    stop_pct = abs(args.entry - args.stop) / args.entry
    decision = can_enter(state, stop_pct, now, override_risk_pct=args.risk_pct)
    if not decision.allowed:
        print(f"\n  ⛔ ENTRY BLOCKED: {decision.reasons[0]}")
        return state
    size = decision.max_size_dollars if args.size is None else min(args.size, decision.max_size_dollars)
    if args.size is not None and args.size > decision.max_size_dollars:
        print(f"  note: requested ${args.size:,.0f} capped to ${size:,.0f} by risk rules.")
    state = register_fill(state, now, args.entry, size)
    print(f"\n  ✅ FILLED {'LONG' if args.stop < args.entry else 'SHORT'} "
          f"${size:,.0f} notional @ ${args.entry:,.2f}, stop ${args.stop:,.2f} "
          f"(stop {stop_pct*100:.2f}% away). Flatten by EOD.")
    return state


def cmd_close(state: RiskState, args) -> RiskState:
    now = _now(args)
    if not state.in_position:
        raise SystemExit("no open position to close. Run 'fill' first.")
    entry = state.position_entry_price
    size = state.position_size
    # pnl on notional: long gains when exit>entry, short gains when exit<entry
    move = (args.exit - entry) / entry if args.side == "long" else (entry - args.exit) / entry
    pnl = size * move
    state = register_close(state, now, args.exit, pnl, mae_pct=min(0.0, args.mae))
    # Log to journal.csv (strat=funded) so journal.py scores the real track record.
    _log_journal(args, entry, size)
    s = status_summary(state)
    print(f"\n  CLOSED @ ${args.exit:,.2f}  ->  PnL ${pnl:+,.0f}   "
          f"equity ${s['current_equity']:,.0f}")
    if s["eval_passed"]:
        print("  ✅ EVAL PASSED — target hit. Stop trading; bank it.")
    elif s["eval_failed"]:
        print(f"  ❌ EVAL FAILED — {s['failure_reason']}")
    elif s["daily_locked_out"]:
        print("  ⛔ daily-loss lockout — no more entries today.")
    return state


def _log_journal(args, entry: float, size_dollars: float) -> None:
    """Append a closed trade to journal.csv in journal.py's format (units≈notional/entry)."""
    units = max(1.0, round(size_dollars / entry, 4))
    row = {
        "logged_at": date.today().isoformat(), "strat": "funded",
        "symbol": args.symbol.upper(), "side": args.side,
        "entry": entry, "exit": args.exit, "size": units, "fee_bps": args.fee_bps,
        "date_in": date.today().isoformat(), "date_out": date.today().isoformat(),
        "note": "funded_forward",
    }
    new = not os.path.exists(JOURNAL_FILE)
    import csv
    with open(JOURNAL_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=journal.FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"  logged to {JOURNAL_FILE} (strat=funded) — score it: "
          f"python journal.py stats --strat funded")


def cmd_status(state: RiskState, args) -> RiskState:
    print(f"\n=== FUNDED STATUS ===")
    for k, v in status_summary(state).items():
        print(f"  {k:<28} {v}")
    print(f"  days_remaining(buffer)       {days_remaining(state)}")
    return state


def cmd_reset(state: RiskState, args) -> RiskState:
    """Archive the finished attempt and start fresh (a new cheap-reset attempt)."""
    if os.path.exists(STATE_FILE):
        os.replace(STATE_FILE, STATE_FILE + ".prev")
    fresh = load_state("___none___", args.firm, args.account)
    print(f"\n  fresh attempt started on {fresh.config.name} "
          f"(account ${args.account:,.0f}). Prior attempt archived to {STATE_FILE}.prev")
    return fresh


def main() -> None:
    p = argparse.ArgumentParser(description="Funded eval forward-test (paper, risk-enforced).")
    p.add_argument("--firm", default=DEFAULT_FIRM, choices=list(FIRMS),
                   help=f"firm rule set (default {DEFAULT_FIRM}; see FUNDED_EVAL.md)")
    p.add_argument("--account", type=float, default=50_000.0)
    p.add_argument("--now", default=None, help="override 'now' (ISO) for testing/cron")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("plan", help="today's disciplined plan").set_defaults(func=cmd_plan)
    sub.add_parser("status", help="full eval snapshot").set_defaults(func=cmd_status)

    f = sub.add_parser("fill", help="open a paper position (size auto-capped to rules)")
    f.add_argument("--entry", type=float, required=True)
    f.add_argument("--stop", type=float, required=True)
    f.add_argument("--size", type=float, default=None, help="notional $ (capped to max)")
    f.add_argument("--risk-pct", type=float, default=None, dest="risk_pct")
    f.set_defaults(func=cmd_fill)

    c = sub.add_parser("close", help="close the open position + log to journal")
    c.add_argument("--exit", type=float, required=True)
    c.add_argument("--side", default="long", choices=("long", "short"))
    c.add_argument("--mae", type=float, default=0.0, help="max adverse excursion %% (<=0)")
    c.add_argument("--symbol", default="NQ")
    c.add_argument("--fee-bps", type=float, default=1.0, dest="fee_bps")
    c.set_defaults(func=cmd_close)

    r = sub.add_parser("reset", help="start a fresh attempt")
    r.add_argument("--firm", default=DEFAULT_FIRM, choices=list(FIRMS))
    r.add_argument("--account", type=float, default=50_000.0)
    r.set_defaults(func=cmd_reset)

    args = p.parse_args()
    state = (load_state("___none___", args.firm, args.account) if args.cmd == "reset"
             else load_state(STATE_FILE, args.firm, args.account))
    state = args.func(state, args)
    save_state(STATE_FILE, state)


if __name__ == "__main__":
    main()
