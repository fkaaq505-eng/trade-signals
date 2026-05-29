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
    mae_pct: float       # max adverse excursion: deepest underwater vs entry (<=0)
    mfe_pct: float       # max favorable excursion: highest unrealized vs entry (>=0)


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
    down_days: int = 2,
    scale_in: bool = False,
    add_rsi: float = 5.0,
    base_frac: float = 0.5,
    add_frac: float = 0.5,
    vix: pd.Series | None = None,
    vix_min: float = 0.0,
    vix_max: float = inf,
    eod_flat: bool = False,
) -> tuple[list[Trade], pd.Series]:
    # No leverage (paper-honest): deployed capital can never exceed 1.0.
    if scale_in and base_frac + add_frac > 1.0 + 1e-9:
        raise ValueError(
            f"scale-in base_frac + add_frac = {base_frac + add_frac} > 1.0 "
            f"(would use leverage; this tool is paper-only, no margin)."
        )
    if scale_in and (base_frac <= 0.0 or add_frac <= 0.0):
        raise ValueError("scale-in fractions must be positive.")

    data = build_indicators(df, strategy=strategy, session=session,
                            rsi_buy=rsi_buy, rsi_exit=rsi_exit, down_days=down_days)
    # Optional VIX-regime gate: only take entries while vix_min <= VIX <= vix_max.
    # Aligned to the price calendar; gate is off unless a vix series is passed.
    use_vix = vix is not None
    if use_vix:
        data = data.assign(vix=vix.reindex(data.index).ffill())
    # EOD-flat (funded/prop rule): never hold overnight. Mark the last bar of each
    # trading day so the loop can force a close there. Intraday data only.
    if eod_flat:
        bar_date = data.index.to_series().dt.date
        data = data.assign(is_day_final=(bar_date != bar_date.shift(-1)))
    round_turn = 2.0 * fee_bps / 10_000.0
    use_stop = sl_mult > 0
    fixed_target = strategy == "trend"

    trades: list[Trade] = []
    equity_curve: list[float] = []
    equity = 1.0

    in_pos = False
    stop = target = 0.0
    entry_ts = None
    tranches: list[tuple[float, float]] = []   # [(fill_price, capital_fraction)]
    pos_low = pos_high = entry_px = 0.0         # for MAE/MFE excursion tracking

    def close_trade(exit_price, exit_ts, reason):
        nonlocal equity, in_pos, tranches
        invested = sum(f for _, f in tranches)
        # Realized value of the deployed fraction; the uninvested (1-invested)
        # sits in cash and earns nothing. Fees hit only the traded portion.
        realized = sum(f * (exit_price / p) for p, f in tranches)
        avg_entry = sum(f * p for p, f in tranches) / invested
        equity *= (1.0 - invested) + realized * (1.0 - round_turn)
        risk = avg_entry - stop if use_stop else 0.0
        r = (exit_price - avg_entry) / risk if risk > 0 else 0.0
        pnl_pct = 100.0 * (realized / invested - 1.0)   # return on invested capital
        # Excursions vs the INITIAL entry price (what a funded-account drawdown
        # limit actually watches — how deep underwater the trade went intraday).
        mae = 100.0 * (pos_low / entry_px - 1.0) if entry_px else 0.0
        mfe = 100.0 * (pos_high / entry_px - 1.0) if entry_px else 0.0
        trades.append(Trade(
            str(entry_ts), str(exit_ts), round(avg_entry, 2), round(exit_price, 2),
            round(stop, 2) if use_stop else None,
            round(target, 2) if fixed_target else None,
            reason, round(r, 2), round(pnl_pct, 2),
            round((exit_ts - entry_ts).total_seconds() / 3600.0, 1),
            round(mae, 2), round(mfe, 2),
        ))
        in_pos = False
        tranches = []

    for ts, row in data.iterrows():
        if in_pos:
            pos_low = min(pos_low, float(row["Low"]))
            pos_high = max(pos_high, float(row["High"]))
            elapsed = (ts - entry_ts).total_seconds() / 3600.0
            if use_stop and row["Low"] <= stop:
                close_trade(stop, ts, "stop")
            elif fixed_target and row["High"] >= target:
                close_trade(target, ts, "target")
            elif elapsed >= max_hold_hours:
                close_trade(float(row["Close"]), ts, "time")
            elif bool(row["raw_sell"]):
                close_trade(float(row["Close"]), ts, "signal")
            elif eod_flat and bool(row["is_day_final"]):
                close_trade(float(row["Close"]), ts, "eod")   # flat overnight
            elif (scale_in and len(tranches) < 2
                  and float(row["disp_rsi"]) < add_rsi
                  and float(row["Close"]) < tranches[-1][0]):
                # Deeper-oversold add (Connors scale-in): one extra tranche on a
                # lower close. raw_sell (RSI2>exit) and this are mutually exclusive.
                tranches.append((float(row["Close"]), add_frac))

        if not in_pos and bool(row["raw_buy"]) and row["atr"] > 0:
            # Event-risk filter: skip entries on high-impact macro days (no
            # network in backtest -> finnhub_key="" so only FOMC/NFP rules apply).
            blocked = skip_events and high_impact_events(ts.date(), finnhub_key="")
            if use_vix and not (vix_min <= float(row["vix"]) <= vix_max):
                blocked = True   # VIX regime out of band -> stand aside
            if not blocked:
                entry = float(row["Close"])
                stop = entry - sl_mult * float(row["atr"]) if use_stop else -inf
                target = entry + reward_risk * (entry - stop) if fixed_target else inf
                entry_ts = ts
                entry_px = entry
                pos_low = pos_high = entry      # track excursions from entry close
                tranches = [(entry, base_frac if scale_in else 1.0)]
                in_pos = True

        equity_curve.append(equity)

    if in_pos:
        close_trade(float(data.iloc[-1]["Close"]), data.index[-1], "end")

    return trades, pd.Series(equity_curve, index=data.index)


def live_signal(df: pd.DataFrame, strategy: str = "trend",
                sl_mult: float = ATR_SL_MULT, reward_risk: float = REWARD_RISK,
                session: str = "us_morning", rsi_buy: float = 10.0,
                rsi_exit: float = 75.0, down_days: int = 2) -> LiveSignal:
    data = build_indicators(df, strategy=strategy, session=session,
                            rsi_buy=rsi_buy, rsi_exit=rsi_exit, down_days=down_days)
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
