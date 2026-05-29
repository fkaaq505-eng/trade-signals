"""
Indicators + signal logic. Pure functions: every function returns a NEW
DataFrame and never mutates its input (immutable style).

Two selectable strategies:

  "trend"   — EMA(20/50) crossover + RSI filter + 200EMA regime + session gate,
              intraday, ATR stop/target. Fast trades. (Weak edge on indices.)

  "meanrev" — Larry Connors RSI(2) mean reversion (daily): only long above the
              200-day SMA, buy when RSI(2) < 10, exit when RSI(2) > 65. This is
              the researched high-win-rate index strategy (docs cite ~75% wins
              and outperformance vs buy-hold). No hard stop in the original.
              Refs: quantifiedstrategies.com/rsi-2-strategy , /connors-rsi

Every builder exposes the SAME downstream columns so the engine/live reader are
strategy-agnostic: raw_buy, raw_sell, atr, disp_rsi, in_trend_ok, above_regime_ok.
"""

from __future__ import annotations

import pandas as pd

from sessions import in_session_mask

# --- "trend" strategy defaults ----------------------------------------------
FAST_EMA = 20
SLOW_EMA = 50
TREND_EMA = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
RSI_ENTRY_MIN = 50.0
RSI_ENTRY_MAX = 70.0
ATR_SL_MULT = 1.2
REWARD_RISK = 1.5

# --- "meanrev" (Connors RSI2) defaults --------------------------------------
MR_RSI_PERIOD = 2
MR_RSI_BUY = 10.0      # buy when RSI(2) below this (Connors uses 5–10)
MR_RSI_EXIT = 65.0     # exit when RSI(2) above this
MR_TREND_SMA = 200


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()  # Wilder
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)


def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    high, low, prev_close = df["High"], df["Low"], df["Close"].shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, adjust=False).mean()


def _finalize(out, raw_buy, raw_sell, disp_rsi, in_trend_ok, above_regime_ok):
    out["raw_buy"] = raw_buy
    out["raw_sell"] = raw_sell
    out["disp_rsi"] = disp_rsi
    out["in_trend_ok"] = in_trend_ok
    out["above_regime_ok"] = above_regime_ok
    return out


def build_trend(df: pd.DataFrame, session: str = "us_morning") -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["Close"], FAST_EMA)
    out["ema_slow"] = ema(out["Close"], SLOW_EMA)
    out["ema_trend"] = ema(out["Close"], TREND_EMA)
    out["atr"] = atr(out, ATR_PERIOD)
    rsi14 = rsi(out["Close"], RSI_PERIOD)

    cross_up = (out["ema_fast"] > out["ema_slow"]) & (
        out["ema_fast"].shift(1) <= out["ema_slow"].shift(1))
    cross_down = (out["ema_fast"] < out["ema_slow"]) & (
        out["ema_fast"].shift(1) >= out["ema_slow"].shift(1))
    rsi_ok = rsi14.between(RSI_ENTRY_MIN, RSI_ENTRY_MAX)
    uptrend = out["Close"] > out["ema_trend"]
    session_ok = in_session_mask(out.index, session)

    raw_buy = cross_up & rsi_ok & uptrend & session_ok
    raw_sell = cross_down
    return _finalize(out, raw_buy, raw_sell, rsi14,
                     out["ema_fast"] > out["ema_slow"], uptrend)


def build_meanrev(df: pd.DataFrame, rsi_buy: float = MR_RSI_BUY,
                  rsi_exit: float = MR_RSI_EXIT,
                  trend: int = MR_TREND_SMA) -> pd.DataFrame:
    out = df.copy()
    rsi2 = rsi(out["Close"], MR_RSI_PERIOD)
    sma_trend = sma(out["Close"], trend)
    out["rsi2"] = rsi2
    out["sma_trend"] = sma_trend
    out["atr"] = atr(out, ATR_PERIOD)

    uptrend = out["Close"] > sma_trend
    raw_buy = uptrend & (rsi2 < rsi_buy)
    raw_sell = rsi2 > rsi_exit
    return _finalize(out, raw_buy, raw_sell, rsi2, uptrend, uptrend)


def build_indicators(df: pd.DataFrame, strategy: str = "trend",
                     session: str = "us_morning", rsi_buy: float = MR_RSI_BUY,
                     rsi_exit: float = MR_RSI_EXIT) -> pd.DataFrame:
    if strategy == "meanrev":
        return build_meanrev(df, rsi_buy=rsi_buy, rsi_exit=rsi_exit)
    return build_trend(df, session=session)
