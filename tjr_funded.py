"""
TJR method as a LIVE, FUNDED-LEGAL day-trade PLAN (paper only).

HONEST STATUS (do not regress): the TJR session-liquidity + FVG reversal model has
NO validated money edge — tested out-of-sample after fees on real 5.4y SPY/QQQ 5m,
real NQ/ES futures, Dukascopy CFDs, and BTC/ETH: all negative (HANDOFF 16, 19-20;
`tjr_futures.py`/`tjr_bot.py`). This module does NOT claim TJR makes money.

What it IS: passing a funded eval is a DISCIPLINE + VARIANCE game, not an edge game
(P(pass) ≈ the firm's barrier ratio regardless of entry method — see eval_montecarlo.py).
You still need a consistent, funded-LEGAL way to take trades, and TJR is exactly that:
  - intraday (no overnight), hard stop (beyond the raid), defined target (opposite
    liquidity pool), EOD-flat, one setup/day → fits every prop rulebook.
This turns the TJR method into today's concrete plan, sized by the risk engine to the
firm's drawdown buffer. It frames the CONDITIONAL setup (like an ORB plan) — you only
trade if price actually raids a pool and reverses with an FVG. No raid = no trade.

    python tjr_funded.py                 # MNQ (default), Apex EOD sizing
    python tjr_funded.py MES topstep     # MES, Topstep sizing

Liquidity pools = prior completed day's high/low (PDH/PDL) — the cleanest stock/
futures analog of "session liquidity" for a once-a-day plan. Data: free Yahoo NQ=F /
ES=F (the micros track these 1:1). NEVER places an order.
"""

from __future__ import annotations

import sys
from datetime import datetime
from math import floor
from zoneinfo import ZoneInfo

import pandas as pd

from data import fetch

ET = ZoneInfo("America/New_York")
AST = ZoneInfo("Asia/Riyadh")

# instrument -> ($ per index point, Yahoo proxy). Micros are 1/10 of the e-mini.
INSTRUMENTS = {
    "MNQ": (2.0, "NQ=F"), "NQ": (20.0, "NQ=F"),
    "MES": (5.0, "ES=F"), "ES": (50.0, "ES=F"),
}
ATR_LEN = 14
MAX_RR = 5.0          # cap the opposite-pool target so R:R framing stays sane
RTH_CLOSE_ET = (15, 55)   # flatten by 15:55 ET (before the 16:00 cash close)


def _atr_points(df: pd.DataFrame, length: int = ATR_LEN) -> float:
    """Average true range in index points on the bar timeframe (volatility => stop size)."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()],
                   axis=1).max(axis=1)
    return float(tr.tail(length).mean())


def _prior_day_pools(df: pd.DataFrame) -> tuple[float, float, str]:
    """Prior completed calendar day's high/low (the liquidity pools) + that day's date."""
    by_day = df.groupby(df.index.normalize())
    days = sorted(by_day.groups)
    if len(days) < 2:
        raise SystemExit("not enough data for prior-day pools")
    prior = days[-2]                      # last fully-completed day
    d = df.loc[df.index.normalize() == prior]
    return float(d["High"].max()), float(d["Low"].min()), str(prior.date())


def _et_ast(hh: int, mm: int) -> str:
    et = datetime.now(ET).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return f"{hh:02d}:{mm:02d} ET / {et.astimezone(AST):%H:%M} AST"


def build_plan(symbol: str = "MNQ", account: float = 50_000.0,
               risk_pct: float = 0.75) -> dict:
    """Today's funded-legal TJR plan: pools, both conditional setups, sizing, R:R."""
    symbol = symbol.upper()
    if symbol not in INSTRUMENTS:
        raise SystemExit(f"symbol must be one of {list(INSTRUMENTS)} (micros recommended)")
    point_value, proxy = INSTRUMENTS[symbol]
    df = fetch(proxy, "60d", "5m")
    pdh, pdl, pday = _prior_day_pools(df)
    atr = _atr_points(df)
    last = float(df["Close"].iloc[-1])

    # Stop sits beyond the raid extreme; estimate its distance from recent volatility.
    stop_pts = round(max(2.0 * atr, 0.05 * (pdh - pdl)), 2)
    risk_dollars = account * risk_pct / 100.0
    per_contract_risk = stop_pts * point_value
    contracts = max(0, floor(risk_dollars / per_contract_risk)) if per_contract_risk > 0 else 0
    actual_risk = contracts * per_contract_risk
    reward_pts = pdh - pdl                       # entry near one pool, target the other
    rr = min(reward_pts / stop_pts, MAX_RR) if stop_pts > 0 else 0.0

    def setup(side: str, pool: float, stop_ref: float, target: float) -> dict:
        return {"side": side, "raid_level": round(pool, 2),
                "stop": round(stop_ref, 2), "target": round(target, 2)}

    return {
        "symbol": symbol, "proxy": proxy, "point_value": point_value,
        "prior_day": pday, "pdh": round(pdh, 2), "pdl": round(pdl, 2),
        "last": round(last, 2), "atr_pts": round(atr, 2),
        "stop_pts": stop_pts, "reward_pts": round(reward_pts, 2), "rr": round(rr, 2),
        "contracts": contracts, "risk_dollars": round(actual_risk, 2),
        "risk_pct": risk_pct, "account": account,
        "flat_by": _et_ast(*RTH_CLOSE_ET),
        # SHORT: price raids ABOVE PDH then reverses (bearish FVG) -> short, target PDL.
        "short": setup("SHORT", pdh, pdh + stop_pts, pdl),
        # LONG: price raids BELOW PDL then reverses (bullish FVG) -> long, target PDH.
        "long": setup("LONG", pdl, pdl - stop_pts, pdh),
    }


def format_plan(p: dict) -> str:
    lines = [
        f"=== TJR FUNDED PLAN — {p['symbol']} (paper · no proven edge · discipline play) ===",
        f"liquidity pools from {p['prior_day']}:  PDH {p['pdh']}   PDL {p['pdl']}   (now {p['last']})",
        f"size: {p['contracts']} {p['symbol']} = ${p['risk_dollars']:,.0f} risk "
        f"({p['risk_pct']}% of ${p['account']:,.0f}) · stop {p['stop_pts']} pts · R:R ~{p['rr']}:1",
        "",
        f"🔴 SHORT setup: price RAIDS above PDH {p['pdh']} then reverses w/ a bearish FVG",
        f"     enter at the FVG · stop {p['short']['stop']} (above the raid) · target PDL {p['short']['target']}",
        f"🟢 LONG setup:  price RAIDS below PDL {p['pdl']} then reverses w/ a bullish FVG",
        f"     enter at the FVG · stop {p['long']['stop']} (below the raid) · target PDH {p['long']['target']}",
        "",
        f"RULES: one setup/day · NO raid+FVG = NO trade · flat by {p['flat_by']}",
        "Confirm the reversal (break of structure + fair-value gap) before entering.",
        "⚠️ TJR has NO validated edge — this is a funded-LEGAL, disciplined way to take the",
        "   trade and ride the eval's variance. It does not make money. Log it: journal.py.",
    ]
    return "\n".join(lines)


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "MNQ"
    # optional firm arg only changes the risk %/account via FUNDED_EVAL defaults; keep simple
    account = float(sys.argv[3]) if len(sys.argv) > 3 else 50_000.0
    print("\n" + format_plan(build_plan(symbol, account)))


if __name__ == "__main__":
    main()
