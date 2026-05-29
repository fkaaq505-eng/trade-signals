"""
Backtest engine + live signal reader. Strategy-agnostic: reads raw_buy/raw_sell
/atr from whichever strategy built the frame.

It NEVER places an order — it simulates and reports, or tells you what the rules
say RIGHT NOW. Acting on it is 100% your decision.

Exit priority each bar: stop (if enabled) -> fixed target (if enabled) ->
wall-clock time-stop -> strategy exit signal (raw_sell).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf

import pandas as pd

from news import high_impact_events
from sessions import in_session_mask
from strategy import ATR_SL_MULT, REWARD_RISK, build_indicators


@dataclass(frozen=True)
class Trade:
    entry_date: str
    exit_date: str
    entry: float
    exit: float
    stop: float | None
    target: float | None
    reason: str          # "target" | "stop" | "time" | "signal" | "end"
    r_multiple: float
    pnl_pct: float
    hold_hours: float


@dataclass(frozen=True)
class LiveSignal:
    as_of: str
    price: float
    in_trend: bool
    above_regime: bool
    action: str
    rsi: float
    session: str
    tradeable_now: bool
    suggested_stop: float | None
    suggested_target: float | None


def backtest(
    df: pd.DataFrame,
    strategy: str = "trend",
    sl_mult: float = ATR_SL_MULT,
    reward_risk: float = REWARD_RISK,
    max_hold_hours: float = 48.0,
    fee_bps: float = 1.0,
    session: str = "us_morning",
    rsi_buy: float = 10.0,
    rsi_exit: float = 75.0,
    skip_events: bool = False,
) -> tuple[list[Trade], pd.Series]:
    data = build_indicators(df, strategy=strategy, session=session,
                            rsi_buy=rsi_buy, rsi_exit=rsi_exit)
    round_turn = 2.0 * fee_bps / 10_000.0
    use_stop = sl_mult > 0
    fixed_target = strategy == "trend"

    trades: list[Trade] = []
    equity_curve: list[float] = []
    equity = 1.0

    in_pos = False
    entry = stop = target = 0.0
    entry_ts = None

    def close_trade(exit_price, exit_ts, reason):
        nonlocal equity, in_pos
        risk = entry - stop if use_stop else 0.0
        r = (exit_price - entry) / risk if risk > 0 else 0.0
        equity *= (exit_price / entry) * (1.0 - round_turn)
        trades.append(Trade(
            str(entry_ts), str(exit_ts), round(entry, 2), round(exit_price, 2),
            round(stop, 2) if use_stop else None,
            round(target, 2) if fixed_target else None,
            reason, round(r, 2), round(100.0 * (exit_price / entry - 1.0), 2),
            round((exit_ts - entry_ts).total_seconds() / 3600.0, 1),
        ))
        in_pos = False

    for ts, row in data.iterrows():
        if in_pos:
            elapsed = (ts - entry_ts).total_seconds() / 3600.0
            if use_stop and row["Low"] <= stop:
                close_trade(stop, ts, "stop")
            elif fixed_target and row["High"] >= target:
                close_trade(target, ts, "target")
            elif elapsed >= max_hold_hours:
                close_trade(float(row["Close"]), ts, "time")
            elif bool(row["raw_sell"]):
                close_trade(float(row["Close"]), ts, "signal")

        if not in_pos and bool(row["raw_buy"]) and row["atr"] > 0:
            # Event-risk filter: skip entries on high-impact macro days (no
            # network in backtest -> finnhub_key="" so only FOMC/NFP rules apply).
            blocked = skip_events and high_impact_events(ts.date(), finnhub_key="")
            if not blocked:
                entry = float(row["Close"])
                stop = entry - sl_mult * float(row["atr"]) if use_stop else -inf
                target = entry + reward_risk * (entry - stop) if fixed_target else inf
                entry_ts = ts
                in_pos = True

        equity_curve.append(equity)

    if in_pos:
        close_trade(float(data.iloc[-1]["Close"]), data.index[-1], "end")

    return trades, pd.Series(equity_curve, index=data.index)


def live_signal(df: pd.DataFrame, strategy: str = "trend",
                sl_mult: float = ATR_SL_MULT, reward_risk: float = REWARD_RISK,
                session: str = "us_morning", rsi_buy: float = 10.0,
                rsi_exit: float = 75.0) -> LiveSignal:
    data = build_indicators(df, strategy=strategy, session=session,
                            rsi_buy=rsi_buy, rsi_exit=rsi_exit)
    last = data.iloc[-1]
    price = float(last["Close"])
    use_stop = sl_mult > 0
    fixed_target = strategy == "trend"
    tradeable_now = bool(in_session_mask(data.index, session).iloc[-1])

    if bool(last["raw_buy"]):
        stop = price - sl_mult * float(last["atr"]) if use_stop else None
        target = (price + reward_risk * (price - stop)
                  if (fixed_target and stop is not None) else None)
        return LiveSignal(str(data.index[-1]), round(price, 2),
                          bool(last["in_trend_ok"]), bool(last["above_regime_ok"]),
                          "BUY", round(float(last["disp_rsi"]), 1), session,
                          tradeable_now,
                          round(stop, 2) if stop is not None else None,
                          round(target, 2) if target is not None else None)

    action = "SELL/EXIT" if bool(last["raw_sell"]) else "HOLD"
    return LiveSignal(str(data.index[-1]), round(price, 2),
                      bool(last["in_trend_ok"]), bool(last["above_regime_ok"]),
                      action, round(float(last["disp_rsi"]), 1), session,
                      tradeable_now, None, None)


def stats(trades: list[Trade], equity: pd.Series, buy_hold: pd.Series) -> dict:
    if not trades:
        return {"trades": 0, "note": "no trades (try --session all or a longer --period)"}

    wins = [t for t in trades if t.exit > t.entry]
    losses = [t for t in trades if t.exit <= t.entry]
    gross_win = sum(t.exit - t.entry for t in wins)
    gross_loss = abs(sum(t.exit - t.entry for t in losses))
    holds = pd.Series([t.hold_hours for t in trades])
    n = len(trades)

    def pct(reason: str) -> float:
        return round(100.0 * sum(1 for t in trades if t.reason == reason) / n, 1)

    drawdown = (equity / equity.cummax() - 1.0).min()
    bh_return = float(buy_hold.iloc[-1] / buy_hold.iloc[0] - 1.0)

    return {
        "trades": n,
        "win_rate_%": round(100.0 * len(wins) / n, 1),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else float("inf"),
        "avg_trade_%": round(sum(t.pnl_pct for t in trades) / n, 2),
        "net_return_%(after fees)": round(100.0 * (equity.iloc[-1] - 1.0), 1),
        "buy_hold_return_%": round(100.0 * bh_return, 1),
        "max_drawdown_%": round(100.0 * drawdown, 1),
        "avg_hold_hours": round(float(holds.mean()), 1),
        "median_hold_hours": round(float(holds.median()), 1),
        "hit_target_%": pct("target"),
        "hit_stop_%": pct("stop"),
        "hit_timeout_%": pct("time"),
        "exit_signal_%": pct("signal"),
    }
