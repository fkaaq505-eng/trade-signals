"""
risk_engine.py — Live Risk / Discipline Engine for prop-firm evaluation.

PAPER / RESEARCH ONLY. This module NEVER places orders. It sizes, permits, and
blocks trades based on firm rules. It is the guardrail a disciplined funded trader
would never violate.

Honest disclaimer: this engine does NOT create a trading edge. It preserves
capital and enforces discipline on whatever instrument/signal is used. Most funded
attempts still fail (~90%); this engine maximises survival odds, it does not
guarantee a pass.

Usage in a paper-trading loop:
    state = make_apex_state(account_size=50_000)
    decision = can_enter(state, stop_distance_pct=0.005, timestamp=ts)
    if decision.allowed:
        state = register_fill(state, timestamp=ts, entry_price=price)
    # ... later ...
    state = register_close(state, timestamp=ts, close_price=exit_px, mae_pct=mae)
    state = on_new_day(state, date=next_date)
    if must_flatten(state, now=ts):
        # close all positions
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timezone
from typing import Literal


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RISK_PCT = 0.75           # % of account risked per trade (default)
DEFAULT_MAX_TRADES_PER_DAY = 3    # block new entries beyond this
DEFAULT_EOD_CUTOFF_MINUTES = 15   # minutes before session close -> no new entries
CONSISTENCY_RATIO_LIMIT = 0.50    # single-day profit cannot exceed 50% of cumulative
MIN_RISK_PCT = 0.001              # guard: reject if stop_distance is essentially zero
MAX_RISK_PCT_CAP = 3.0            # sanity cap: never risk more than 3% regardless


# ---------------------------------------------------------------------------
# Firm presets
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FirmConfig:
    """
    Immutable configuration for a specific prop firm evaluation.

    All pct fields are expressed as percentages of account (e.g. 4.0 = 4%).

    trailing_dd_mode: "intraday" (Apex) or "eod" (Topstep).
        - "intraday": peak trails DURING each trade using the trade's MAE
          (worst intraday equity dip). This is the Apex 4.0 hard mode.
        - "eod": peak only updates at end of day based on closing equity.
          Drawdown is never watched intraday. This is the Topstep 2026 mode.

    daily_loss_limit_pct: firm's maximum permitted daily loss.
    trailing_dd_pct: maximum trailing drawdown from peak (absolute, not per-day).
    profit_target_pct: profit target to pass the evaluation.
    max_eval_days: maximum calendar days allowed for the evaluation.
    session_close: (hour, minute) in UTC for mandatory EOD-flat.

    NOTE: Rules change. Always verify against the firm's current rulebook before
    risking a real evaluation fee. Apex 4.0 and Topstep 2026 values are used here
    as widely-documented defaults (as of 2026-03-01).
    """
    name: str
    trailing_dd_pct: float              # e.g. 4.0 for Apex 50k
    daily_loss_limit_pct: float         # e.g. 2.0 for Apex
    profit_target_pct: float            # e.g. 6.0 for Apex 50k
    max_eval_days: int                  # e.g. 30 for Apex
    trailing_dd_mode: Literal["intraday", "eod"]
    session_close: tuple[int, int]      # (hour, minute) UTC e.g. (21, 0) = 4pm ET
    eod_flat_mandatory: bool
    consistency_ratio_limit: float      # e.g. 0.50 = no day > 50% of total profit
    per_trade_risk_pct: float           # default per-trade risk (self-imposed)
    max_trades_per_day: int


# Apex Trader Funding — 50k account, Standard Plan (Apex 4.0 as of 2026-03)
# Source: apextraderfunding.com standard plan rules.
# VERIFY before use: firm rules change; this is a research default.
APEX_50K = FirmConfig(
    name="Apex Trader Funding 50k (Standard, Apex 4.0)",
    trailing_dd_pct=2.5,          # $1,250 trailing drawdown on 50k (2.5%)
    daily_loss_limit_pct=1.5,     # $750 daily loss limit
    profit_target_pct=6.0,        # $3,000 profit target (6%)
    max_eval_days=30,
    trailing_dd_mode="intraday",  # Apex watches intraday lows — the hard mode
    session_close=(21, 0),        # 4pm ET / 9pm UTC (approximate, verify DST)
    eod_flat_mandatory=True,
    consistency_ratio_limit=0.50,
    per_trade_risk_pct=0.75,
    max_trades_per_day=3,
)

# Apex Trader Funding — 100k account (more margin, same trailing structure)
# VERIFY before use.
APEX_100K = FirmConfig(
    name="Apex Trader Funding 100k (Standard, Apex 4.0)",
    trailing_dd_pct=2.5,          # $2,500 trailing drawdown (2.5%)
    daily_loss_limit_pct=1.5,
    profit_target_pct=6.0,
    max_eval_days=30,
    trailing_dd_mode="intraday",
    session_close=(21, 0),
    eod_flat_mandatory=True,
    consistency_ratio_limit=0.50,
    per_trade_risk_pct=0.75,
    max_trades_per_day=3,
)

# Topstep — 50k account (Express plan 2026)
# Source: topstep.com express evaluation rules.
# Topstep uses EOD-trailing (easier to survive than Apex intraday).
# VERIFY before use.
TOPSTEP_50K = FirmConfig(
    name="Topstep 50k (Express, EOD-trailing, 2026)",
    trailing_dd_pct=4.0,          # $2,000 trailing drawdown (4%)
    daily_loss_limit_pct=2.0,     # $1,000 daily loss limit
    profit_target_pct=6.0,        # $3,000 profit target
    max_eval_days=60,
    trailing_dd_mode="eod",       # Topstep: peak trails only at end of day
    session_close=(21, 0),
    eod_flat_mandatory=True,
    consistency_ratio_limit=0.50,
    per_trade_risk_pct=0.75,
    max_trades_per_day=3,
)

# Topstep — 100k account
# VERIFY before use.
TOPSTEP_100K = FirmConfig(
    name="Topstep 100k (Express, EOD-trailing, 2026)",
    trailing_dd_pct=4.0,          # $4,000 trailing drawdown (4%)
    daily_loss_limit_pct=2.0,
    profit_target_pct=6.0,
    max_eval_days=60,
    trailing_dd_mode="eod",
    session_close=(21, 0),
    eod_flat_mandatory=True,
    consistency_ratio_limit=0.50,
    per_trade_risk_pct=0.75,
    max_trades_per_day=3,
)


# ---------------------------------------------------------------------------
# Engine state (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DayStats:
    """Realised PnL and trade count for one trading day."""
    trade_date: date
    realized_pnl: float   # cumulative for this day (dollars)
    trade_count: int


@dataclass(frozen=True)
class RiskState:
    """
    Complete, immutable snapshot of the risk engine at a point in time.

    All dollar values are in the same currency as account_size.
    Do not mutate — use the update functions which return new states.
    """
    config: FirmConfig

    # Account metrics
    account_size: float     # initial account size (never changes)
    current_equity: float   # current equity after all closed trades
    equity_peak: float      # highest equity ever seen (trails with mode)

    # Evaluation progress
    start_date: date
    current_date: date
    cumulative_profit: float    # total realized profit (current_equity - account_size)

    # Daily tracking
    today_stats: DayStats

    # Per-day profit history for consistency check {date: profit}
    daily_profit_history: tuple[tuple[date, float], ...]

    # Status flags
    daily_locked_out: bool      # True = hit daily loss limit; reset on_new_day
    eval_passed: bool
    eval_failed: bool
    failure_reason: str         # non-empty if eval_failed

    # Open position tracking
    in_position: bool
    position_entry_price: float
    position_size: float        # units/contracts (informational, not used in sizing calc)
    position_entry_ts: datetime | None


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def make_state(config: FirmConfig, account_size: float, start_date: date) -> RiskState:
    """Create an initial RiskState for the given firm config and account size."""
    _validate_account_size(account_size)
    today = DayStats(trade_date=start_date, realized_pnl=0.0, trade_count=0)
    return RiskState(
        config=config,
        account_size=account_size,
        current_equity=account_size,
        equity_peak=account_size,
        start_date=start_date,
        current_date=start_date,
        cumulative_profit=0.0,
        today_stats=today,
        daily_profit_history=(),
        daily_locked_out=False,
        eval_passed=False,
        eval_failed=False,
        failure_reason="",
        in_position=False,
        position_entry_price=0.0,
        position_size=0.0,
        position_entry_ts=None,
    )


def make_apex_state(account_size: float = 50_000.0,
                    start_date: date | None = None,
                    plan: Literal["50k", "100k"] = "50k") -> RiskState:
    """Convenience factory: Apex 4.0 intraday-trailing config."""
    cfg = APEX_50K if plan == "50k" else APEX_100K
    return make_state(cfg, account_size, start_date or date.today())


def make_topstep_state(account_size: float = 50_000.0,
                       start_date: date | None = None,
                       plan: Literal["50k", "100k"] = "50k") -> RiskState:
    """Convenience factory: Topstep 2026 EOD-trailing config."""
    cfg = TOPSTEP_50K if plan == "50k" else TOPSTEP_100K
    return make_state(cfg, account_size, start_date or date.today())


# ---------------------------------------------------------------------------
# Decision type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """
    Result of can_enter(). Read-only. If allowed=False, reasons explains why.
    max_size is the maximum position size in dollar terms (not units).
    """
    allowed: bool
    max_size_dollars: float   # 0.0 if not allowed
    reasons: tuple[str, ...]  # always populated with at least one entry
    risk_pct_used: float      # actual risk % that drove sizing (0.0 if blocked)


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------

def can_enter(
    state: RiskState,
    stop_distance_pct: float,    # stop distance as fraction of entry price, e.g. 0.005
    timestamp: datetime,
    override_risk_pct: float | None = None,  # override per-trade risk %
) -> Decision:
    """
    Decide whether a new entry is permitted and compute the maximum position size.

    stop_distance_pct: the distance from entry to stop as a fraction of entry price
        (e.g. 0.005 means the stop is 0.5% below entry).

    Returns a Decision. Never raises; validation issues become blocked decisions.

    PAPER ONLY. This never places an order.
    """
    reasons: list[str] = []

    # --- Eval already concluded ---
    if state.eval_passed:
        return _blocked(reasons, "eval already PASSED — no more trades needed")
    if state.eval_failed:
        return _blocked(reasons, f"eval FAILED: {state.failure_reason}")

    # --- Input validation ---
    if stop_distance_pct <= 0:
        return _blocked(reasons, f"invalid stop_distance_pct={stop_distance_pct:.6f}: must be > 0")
    if stop_distance_pct < MIN_RISK_PCT:
        return _blocked(reasons,
                        f"stop_distance_pct={stop_distance_pct:.6f} is below minimum "
                        f"{MIN_RISK_PCT} — stop is effectively zero, entry rejected")

    # --- Daily lockout ---
    if state.daily_locked_out:
        return _blocked(reasons,
                        "daily-loss lockout active — no entries until next session")

    # --- Already in a position ---
    if state.in_position:
        return _blocked(reasons, "already in a position — flatten first")

    # --- Max trades per day ---
    if state.today_stats.trade_count >= state.config.max_trades_per_day:
        return _blocked(reasons,
                        f"max trades/day reached "
                        f"({state.today_stats.trade_count}/{state.config.max_trades_per_day})")

    # --- EOD-flat: too close to session close ---
    if _near_session_close(timestamp, state.config):
        return _blocked(reasons,
                        f"EOD-flat zone: within {DEFAULT_EOD_CUTOFF_MINUTES} min of "
                        f"session close — no new entries")

    # --- Compute max size from DD buffer ---
    dd_buffer = _remaining_dd_buffer(state)
    if dd_buffer <= 0:
        return _blocked(reasons, f"trailing DD buffer exhausted (buffer=${dd_buffer:.2f})")

    risk_pct = override_risk_pct if override_risk_pct is not None else state.config.per_trade_risk_pct
    risk_pct = min(risk_pct, MAX_RISK_PCT_CAP)

    # Max size from trailing-DD: if we stop out, we cannot breach the buffer.
    # max_size_dd * stop_distance_pct <= dd_buffer
    max_size_from_dd = dd_buffer / stop_distance_pct

    # Max size from per-trade risk %: risk is (account_size * risk_pct / 100)
    risk_dollars = state.current_equity * risk_pct / 100.0
    max_size_from_risk = risk_dollars / stop_distance_pct

    # Take the minimum (most conservative)
    max_size = min(max_size_from_dd, max_size_from_risk)
    binding = "DD-buffer" if max_size_from_dd < max_size_from_risk else f"{risk_pct:.2f}%-risk"

    reasons.append(
        f"allowed: size=${max_size:,.0f} (binding={binding}; "
        f"dd_buffer=${dd_buffer:,.0f}, risk_cap=${max_size_from_risk:,.0f})"
    )

    return Decision(
        allowed=True,
        max_size_dollars=round(max_size, 2),
        reasons=tuple(reasons),
        risk_pct_used=round(risk_pct, 4),
    )


def register_fill(
    state: RiskState,
    timestamp: datetime,
    entry_price: float,
    size_dollars: float,
) -> RiskState:
    """
    Record that a position was opened. Returns new state.

    size_dollars: the notional dollar value of the position (not risk).
    """
    if state.in_position:
        raise ValueError("register_fill called while already in a position")
    if entry_price <= 0:
        raise ValueError(f"entry_price must be > 0, got {entry_price}")
    if size_dollars <= 0:
        raise ValueError(f"size_dollars must be > 0, got {size_dollars}")

    return replace(
        state,
        in_position=True,
        position_entry_price=entry_price,
        position_size=size_dollars,
        position_entry_ts=timestamp,
    )


def register_close(
    state: RiskState,
    timestamp: datetime,
    close_price: float,
    pnl_dollars: float,
    mae_pct: float = 0.0,   # max adverse excursion as % of entry price (negative or 0)
) -> RiskState:
    """
    Record that the open position was closed. Returns new state.

    pnl_dollars: realised profit/loss for this trade (negative = loss).
    mae_pct: worst intraday move against the position as % of entry price (<= 0).
        Used for Apex intraday-trailing drawdown tracking.

    Side effects modelled (all in the returned state):
      - Updates current_equity and cumulative_profit.
      - Updates equity_peak (mode-dependent).
      - Checks trailing-DD breach (intraday if Apex, eod if Topstep).
      - Updates today_stats.
      - Checks daily-loss limit → sets daily_locked_out if breached.
      - Checks profit target → sets eval_passed.
      - Checks consistency rule.
    """
    if not state.in_position:
        raise ValueError("register_close called but no position is open")
    if close_price <= 0:
        raise ValueError(f"close_price must be > 0, got {close_price}")
    if mae_pct > 0:
        raise ValueError(f"mae_pct should be <= 0 (adverse = negative), got {mae_pct}")

    new_equity = state.current_equity + pnl_dollars
    new_cumulative = new_equity - state.account_size

    # --- Trailing drawdown check ---
    # Intraday mode (Apex): the intraday equity low = current_equity + position notional * mae_pct
    # EOD mode (Topstep): peak only updates at EOD via on_new_day; breach checked at close
    intraday_equity_low = _compute_intraday_low(state, mae_pct)
    trailing_dd_limit = state.account_size * state.config.trailing_dd_pct / 100.0
    current_peak = state.equity_peak

    failed = False
    failure_reason = ""

    if state.config.trailing_dd_mode == "intraday":
        # Apex: did the intraday low breach the trailing limit from the peak?
        if current_peak - intraday_equity_low > trailing_dd_limit:
            failed = True
            breach = current_peak - intraday_equity_low
            failure_reason = (
                f"FAIL — Apex intraday trailing-DD breached: "
                f"peak=${current_peak:,.0f}, intraday_low=${intraday_equity_low:,.0f}, "
                f"breach=${breach:,.0f} > limit=${trailing_dd_limit:,.0f}"
            )
    else:
        # Topstep EOD: check if closing equity is below trailing limit
        if current_peak - new_equity > trailing_dd_limit:
            failed = True
            breach = current_peak - new_equity
            failure_reason = (
                f"FAIL — Topstep EOD trailing-DD breached: "
                f"peak=${current_peak:,.0f}, close_equity=${new_equity:,.0f}, "
                f"breach=${breach:,.0f} > limit=${trailing_dd_limit:,.0f}"
            )

    # For intraday mode, update peak after checking (trailing peak updates on new highs)
    new_peak = current_peak
    if not failed:
        new_peak = max(current_peak, new_equity)  # peak updates regardless of mode here

    # --- Today stats update ---
    new_today = DayStats(
        trade_date=state.today_stats.trade_date,
        realized_pnl=state.today_stats.realized_pnl + pnl_dollars,
        trade_count=state.today_stats.trade_count + 1,
    )

    # --- Daily loss limit check ---
    daily_loss_limit = state.account_size * state.config.daily_loss_limit_pct / 100.0
    daily_locked_out = state.daily_locked_out
    if new_today.realized_pnl < -daily_loss_limit:
        daily_locked_out = True
        if not failed:
            # Daily loss doesn't fail the eval outright (just locks the day),
            # but if the loss also breaches the trailing DD it will have been caught above.
            pass

    # --- Profit target check ---
    eval_passed = state.eval_passed
    profit_target = state.account_size * state.config.profit_target_pct / 100.0
    if new_cumulative >= profit_target and not failed:
        eval_passed = True

    # --- Consistency check (warn only — does not block here; use check_consistency separately) ---
    # Reflected in the state; callers should call check_consistency() before the next entry.

    return replace(
        state,
        current_equity=new_equity,
        equity_peak=new_peak,
        cumulative_profit=new_cumulative,
        today_stats=new_today,
        daily_locked_out=daily_locked_out,
        in_position=False,
        position_entry_price=0.0,
        position_size=0.0,
        position_entry_ts=None,
        eval_passed=eval_passed,
        eval_failed=failed,
        failure_reason=failure_reason,
    )


def on_new_day(state: RiskState, new_date: date) -> RiskState:
    """
    Call at the start of each new trading session.

    - Resets daily lockout.
    - Resets today_stats.
    - For EOD-trailing mode (Topstep): updates the equity peak from yesterday's close.
    - Archives yesterday's profit in daily_profit_history.
    - Advances current_date.
    """
    if new_date <= state.current_date:
        raise ValueError(
            f"on_new_day: new_date={new_date} must be after current_date={state.current_date}"
        )

    # Archive yesterday's daily PnL
    yesterday_profit = state.today_stats.realized_pnl
    new_history = state.daily_profit_history + ((state.current_date, yesterday_profit),)

    # EOD-trailing (Topstep): peak only trails to end-of-day equity
    new_peak = state.equity_peak
    if state.config.trailing_dd_mode == "eod":
        new_peak = max(state.equity_peak, state.current_equity)

    new_today = DayStats(trade_date=new_date, realized_pnl=0.0, trade_count=0)

    return replace(
        state,
        current_date=new_date,
        today_stats=new_today,
        daily_profit_history=new_history,
        daily_locked_out=False,   # reset on new day
        equity_peak=new_peak,
    )


def must_flatten(state: RiskState, now: datetime) -> bool:
    """
    Returns True if all positions MUST be closed immediately.

    Triggers: within EOD_CUTOFF_MINUTES of session close, OR eval concluded.
    """
    if state.eval_passed or state.eval_failed:
        return True
    if not state.config.eod_flat_mandatory:
        return False
    return _near_session_close(now, state.config, cutoff_minutes=0)


# ---------------------------------------------------------------------------
# Informational helpers (read-only, no state mutation)
# ---------------------------------------------------------------------------

def remaining_dd_buffer(state: RiskState) -> float:
    """
    Current distance from equity peak before the trailing DD limit is breached.
    Returns a dollar amount. A value <= 0 means the eval is already failed.
    """
    return _remaining_dd_buffer(state)


def days_elapsed(state: RiskState) -> int:
    return (state.current_date - state.start_date).days


def days_remaining(state: RiskState) -> int:
    return max(0, state.config.max_eval_days - days_elapsed(state))


def profit_pace_report(state: RiskState) -> dict:
    """
    Report whether the trader is on a safe pace toward the profit target.

    Returns a dict with:
      - target_dollars: the profit target in $
      - current_profit: realised profit so far
      - pct_complete: progress toward target (%)
      - on_pace: True if average daily profit rate projects to reach target in time
      - days_elapsed / days_remaining
      - required_daily_to_finish: avg $ needed per remaining day
      - safe_pace_note: narrative
    """
    target = state.account_size * state.config.profit_target_pct / 100.0
    elapsed = days_elapsed(state)
    remaining = days_remaining(state)
    pct_complete = 100.0 * state.cumulative_profit / target if target > 0 else 0.0

    if elapsed == 0:
        avg_daily = 0.0
    else:
        avg_daily = state.cumulative_profit / elapsed

    projected = state.cumulative_profit + avg_daily * remaining
    on_pace = projected >= target

    needed_per_day = (
        (target - state.cumulative_profit) / remaining if remaining > 0 else float("inf")
    )

    if remaining <= 0:
        note = "TIME UP — eval clock expired."
    elif on_pace:
        note = (
            f"On pace: projecting ${projected:,.0f} profit vs ${target:,.0f} target. "
            f"Do NOT oversize to accelerate — let the pace work."
        )
    else:
        note = (
            f"Behind pace: need ${needed_per_day:,.0f}/day over {remaining} days. "
            f"WARNING: do not chase the target with larger size — that kills evals. "
            f"Maintain discipline; smaller wins compound; oversizing fails accounts."
        )

    return {
        "target_dollars": round(target, 2),
        "current_profit": round(state.cumulative_profit, 2),
        "pct_complete": round(pct_complete, 1),
        "on_pace": on_pace,
        "days_elapsed": elapsed,
        "days_remaining": remaining,
        "avg_daily_profit": round(avg_daily, 2),
        "required_daily_to_finish": round(needed_per_day, 2) if remaining > 0 else None,
        "safe_pace_note": note,
    }


def check_consistency(state: RiskState, today_pnl_if_trade_wins: float) -> dict:
    """
    Check if a hypothetical trade's profit would violate the firm's consistency rule.

    Many firms (FTMO, etc.) require no single day to exceed ~30-50% of total profit.
    Returns a dict with 'flag' (bool) and 'message'.

    today_pnl_if_trade_wins: what today's total PnL would be if the contemplated trade
        wins. Pass today_stats.realized_pnl + expected_trade_pnl.

    The consistency rule compares today's profit against PRIOR profit (from previous
    days). It is only binding once there is a positive prior profit baseline; on the
    very first profitable day there is nothing prior to compare against.
    """
    limit = state.config.consistency_ratio_limit

    # Prior profit = profit accumulated on previous days (not including today's activity)
    prior_profit = state.cumulative_profit - state.today_stats.realized_pnl

    if prior_profit <= 0:
        return {
            "flag": False,
            "message": "no prior profit from previous days — consistency rule not yet binding",
        }

    # Total profit if this scenario materialises
    future_cumulative = prior_profit + state.today_stats.realized_pnl + max(today_pnl_if_trade_wins, 0)

    if future_cumulative <= 0:
        return {
            "flag": False,
            "message": "no cumulative profit yet — consistency rule not yet binding",
        }

    # Today's projected total pnl as fraction of total projected cumulative
    today_total = state.today_stats.realized_pnl + today_pnl_if_trade_wins
    ratio = today_total / future_cumulative if future_cumulative > 0 else 0.0
    flag = ratio > limit

    return {
        "flag": flag,
        "today_pnl_scenario": round(today_total, 2),
        "future_cumulative": round(future_cumulative, 2),
        "ratio": round(ratio, 3),
        "limit": limit,
        "message": (
            f"CONSISTENCY WARNING: today would be {ratio:.1%} of total profit "
            f"(limit {limit:.0%}). Reduce size or skip to stay compliant."
            if flag else
            f"Consistency OK: today {ratio:.1%} of total profit (limit {limit:.0%})"
        ),
    }


def status_summary(state: RiskState) -> dict:
    """
    Full snapshot of the eval status for display/logging.
    """
    dd_buffer = _remaining_dd_buffer(state)
    trailing_limit = state.account_size * state.config.trailing_dd_pct / 100.0
    daily_limit = state.account_size * state.config.daily_loss_limit_pct / 100.0

    return {
        "firm": state.config.name,
        "trailing_dd_mode": state.config.trailing_dd_mode,
        "account_size": state.account_size,
        "current_equity": round(state.current_equity, 2),
        "equity_peak": round(state.equity_peak, 2),
        "cumulative_profit": round(state.cumulative_profit, 2),
        "profit_target": round(state.account_size * state.config.profit_target_pct / 100, 2),
        "trailing_dd_limit": round(trailing_limit, 2),
        "trailing_dd_buffer_remaining": round(dd_buffer, 2),
        "daily_loss_limit": round(daily_limit, 2),
        "today_pnl": round(state.today_stats.realized_pnl, 2),
        "today_trades": state.today_stats.trade_count,
        "max_trades_per_day": state.config.max_trades_per_day,
        "daily_locked_out": state.daily_locked_out,
        "in_position": state.in_position,
        "eval_passed": state.eval_passed,
        "eval_failed": state.eval_failed,
        "failure_reason": state.failure_reason,
        "days_elapsed": days_elapsed(state),
        "days_remaining": days_remaining(state),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _remaining_dd_buffer(state: RiskState) -> float:
    trailing_limit = state.account_size * state.config.trailing_dd_pct / 100.0
    current_drawdown = state.equity_peak - state.current_equity
    return trailing_limit - current_drawdown


def _compute_intraday_low(state: RiskState, mae_pct: float) -> float:
    """
    Compute the worst equity seen intraday for this trade.

    mae_pct is the max adverse excursion as a % of entry price (negative or 0).
    For intraday-trailing purposes, the equity low = equity_before + position * mae%.
    """
    if not state.in_position or mae_pct == 0.0:
        return state.current_equity
    return state.current_equity + state.position_size * (mae_pct / 100.0)


def _near_session_close(ts: datetime, config: FirmConfig,
                        cutoff_minutes: int = DEFAULT_EOD_CUTOFF_MINUTES) -> bool:
    """Return True if ts is within cutoff_minutes of session close."""
    if not config.eod_flat_mandatory:
        return False
    close_h, close_m = config.session_close
    close_time = time(close_h, close_m)
    if ts.tzinfo is not None:
        ts_utc = ts.astimezone(timezone.utc)
        ts_time = ts_utc.time().replace(second=0, microsecond=0)
    else:
        ts_time = ts.time().replace(second=0, microsecond=0)
    # Minutes since midnight
    ts_mins = ts_time.hour * 60 + ts_time.minute
    close_mins = close_time.hour * 60 + close_time.minute
    return ts_mins >= close_mins - cutoff_minutes


def _blocked(reasons: list[str], reason: str) -> Decision:
    reasons.append(reason)
    return Decision(allowed=False, max_size_dollars=0.0,
                    reasons=tuple(reasons), risk_pct_used=0.0)


def _validate_account_size(account_size: float) -> None:
    if account_size <= 0:
        raise ValueError(f"account_size must be > 0, got {account_size}")
