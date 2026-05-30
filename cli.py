"""
Command-line entry. Fetches free Yahoo data and backtests / prints the signal.

Two strategies:
  --strategy trend    EMA crossover, intraday 1h, fast trades (weak edge)
  --strategy meanrev  Connors RSI(2), daily, high win rate (researched edge)

Usage:
    python cli.py both --strategy meanrev --symbol SPY
    python cli.py both --strategy meanrev --symbol QQQ
    python cli.py live --strategy meanrev --symbol QQQ
    python cli.py both --strategy trend   --symbol SPY --session us_power

NEVER connects to a broker. NEVER places orders. Informational only.
"""

from __future__ import annotations

import argparse
from datetime import date

from data import fetch
from engine import backtest, live_signal, stats
from news import news_block
from sessions import SESSIONS

DEFAULT_SYMBOL = "SPY"   # S&P500=SPY/^GSPC, Nasdaq=QQQ/^NDX/^IXIC

# Per-strategy defaults filled in when the user doesn't pass the flag.
DEFAULTS = {
    "trend":   {"interval": "1h", "period": "730d", "sl_mult": 1.2,
                "max_hold": 48.0, "session": "us_morning"},
    "meanrev": {"interval": "1d", "period": "12y", "sl_mult": 0.0,
                "max_hold": 240.0, "session": "all"},
    "bb":      {"interval": "1d", "period": "12y", "sl_mult": 0.0,
                "max_hold": 240.0, "session": "all"},
}


def resolve(args):
    d = DEFAULTS[args.strategy]
    args.interval = args.interval or d["interval"]
    args.period = args.period or d["period"]
    args.session = args.session or d["session"]
    args.sl_mult = d["sl_mult"] if args.sl_mult is None else args.sl_mult
    args.max_hold_hours = d["max_hold"] if args.max_hold_hours is None else args.max_hold_hours
    if args.skip_events is None:
        args.skip_events = args.strategy in ("meanrev", "bb")  # event filter on for mean reversion
    if args.down_days is None:
        args.down_days = 2 if args.strategy == "meanrev" else 0  # confirmed-pullback filter
    return args


def cmd_backtest(df, args):
    trades, equity = backtest(
        df, strategy=args.strategy, sl_mult=args.sl_mult, reward_risk=args.rr,
        max_hold_hours=args.max_hold_hours, fee_bps=args.fee_bps,
        session=args.session, rsi_buy=args.rsi_buy, rsi_exit=args.rsi_exit,
        skip_events=args.skip_events, down_days=args.down_days,
        scale_in=args.scale_in, add_rsi=args.add_rsi,
        base_frac=args.base_frac, add_frac=args.add_frac)
    buy_hold = df["Close"] / df["Close"].iloc[0]
    s = stats(trades, equity, buy_hold)
    print(f"\n=== BACKTEST: {args.symbol}  strategy={args.strategy}  "
          f"{args.interval}/{args.period} ===")
    for k, v in s.items():
        print(f"  {k:<26} {v}")
    if trades:
        print("\n  last 6 trades:")
        for t in trades[-6:]:
            print(f"    {t.entry_date}  ->  {t.exit_date}  "
                  f"({t.hold_hours}h, {t.reason})  {t.pnl_pct:+}%")


def cmd_live(df, args):
    sig = live_signal(df, strategy=args.strategy, sl_mult=args.sl_mult,
                      reward_risk=args.rr, session=args.session,
                      rsi_buy=args.rsi_buy, rsi_exit=args.rsi_exit,
                      down_days=args.down_days)
    print(f"\n=== LIVE SIGNAL: {args.symbol}  strategy={args.strategy}  (bar {sig.as_of}) ===")
    print(f"  price            {sig.price}")
    print(f"  regime           {'above 200 (long ok)' if sig.above_regime else 'below 200 (no longs)'}")
    print(f"  rsi              {sig.rsi}")
    if args.strategy == "trend":
        print(f"  session          {sig.session}  ({'OPEN now' if sig.tradeable_now else 'CLOSED now'})")
    print(f"  ACTION           {sig.action}")
    if sig.suggested_stop is not None:
        print(f"  -> stop          {sig.suggested_stop}")
    if sig.suggested_target is not None:
        print(f"  -> target        {sig.suggested_target}")
    if args.news:
        nb = news_block([args.symbol], date.today())
        if nb:
            print("\n" + nb)
    print("\n  NOTE: rules-based output, not advice. You decide. Paper-trade first.")


def cmd_funded(args):
    """The MAIN funded-eval flow: show today's disciplined paper plan (risk_engine-
    enforced). Delegates to funded_forward; state persists in funded_state.json.
    Pick the firm with FUNDED_EVAL.md / eval_montecarlo.py (default Apex 4.0 EOD)."""
    import funded_forward as ff
    firm = args.firm if args.firm in ff.FIRMS else ff.DEFAULT_FIRM
    state = ff.load_state(ff.STATE_FILE, firm, args.account)
    state = ff.cmd_plan(state, args)
    ff.save_state(ff.STATE_FILE, state)


def main():
    p = argparse.ArgumentParser(description="Mechanical buy/sell signal tool (no broker, no orders).")
    p.add_argument("mode", choices=["backtest", "live", "both", "funded"])
    p.add_argument("--strategy", default="trend", choices=["trend", "meanrev", "bb"])
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--period", default=None)
    p.add_argument("--interval", default=None)
    p.add_argument("--session", default=None, choices=list(SESSIONS))
    p.add_argument("--max-hold-hours", type=float, default=None)
    p.add_argument("--sl-mult", type=float, default=None, help="0 = no stop (meanrev default)")
    p.add_argument("--rr", type=float, default=1.5)
    p.add_argument("--fee-bps", type=float, default=1.0)
    p.add_argument("--rsi-buy", type=float, default=10.0, help="meanrev: buy when RSI(2) below this")
    p.add_argument("--rsi-exit", type=float, default=75.0, help="meanrev: exit when RSI(2) above this")
    p.add_argument("--skip-events", action=argparse.BooleanOptionalAction, default=None,
                   help="skip entries on high-impact days (FOMC/NFP); on by default for meanrev")
    p.add_argument("--news", action="store_true", help="live: show headlines + event flag")
    p.add_argument("--down-days", type=int, default=None,
                   help="meanrev: require N consecutive down closes before entry (default 2)")
    p.add_argument("--scale-in", action="store_true",
                   help="meanrev: add a deeper-oversold tranche (Connors scale-in, no leverage)")
    p.add_argument("--add-rsi", type=float, default=5.0,
                   help="scale-in: add when RSI(2) below this (default 5)")
    p.add_argument("--base-frac", type=float, default=0.5,
                   help="scale-in: capital fraction at first signal (default 0.5)")
    p.add_argument("--add-frac", type=float, default=0.5,
                   help="scale-in: capital fraction added on deeper dip (default 0.5)")
    p.add_argument("--firm", default="apex_eod",
                   help="funded mode: firm rule set (see FUNDED_EVAL.md / eval_montecarlo.py)")
    p.add_argument("--account", type=float, default=50_000.0,
                   help="funded mode: eval account size (default 50k)")
    p.add_argument("--now", default=None, help="funded mode: override 'now' (ISO, for testing)")
    parsed = p.parse_args()

    # MAIN funded-eval flow — no market fetch needed (risk discipline, not a signal).
    if parsed.mode == "funded":
        cmd_funded(parsed)
        return

    args = resolve(parsed)
    df = fetch(args.symbol, args.period, args.interval)
    if args.mode in ("backtest", "both"):
        cmd_backtest(df, args)
    if args.mode in ("live", "both"):
        cmd_live(df, args)


if __name__ == "__main__":
    main()
