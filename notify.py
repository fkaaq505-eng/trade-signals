"""
Phone-push notifier for trade signals via ntfy.sh (free, no account).
Runs on a cloud cron (GitHub Actions) so it works with your laptop closed.
See NOTIFY.md for setup. It NEVER places an order — you decide and you click.

Two modes:
  (default)  actionable alert — only pushes when a symbol is not HOLD. Meant to
             fire near the US close.
  --brief    always pushes a status summary. Meant for a civil-hour morning
             recap in your timezone (set via a separate cron).
  --force    skip the "is it near the US close?" time gate (for --brief / tests).

Env: NTFY_TOPIC (required for real push), NTFY_SERVER, SYMBOLS, STRATEGY.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from data import fetch
from engine import live_signal
from news import fetch_headlines, high_impact_events
from strategy import ATR_SL_MULT

ET = ZoneInfo("America/New_York")
def _load_symbols() -> list[str]:
    """watchlist.txt (one symbol per line) wins; else SYMBOLS env; else SPY.
    The repo file lets us change the watchlist without touching the workflow."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "watchlist.txt")
    if os.path.exists(path):
        with open(path) as f:
            syms = [ln.strip().upper() for ln in f if ln.strip() and not ln.startswith("#")]
        if syms:
            return syms
    return [s.strip() for s in os.environ.get("SYMBOLS", "SPY").split(",") if s.strip()]


SYMBOLS = _load_symbols()
STRATEGY = os.environ.get("STRATEGY", "meanrev")
# Mean reversion is validated with NO stop (a stop wrecks its win rate); only the
# intraday "trend" strategy uses an ATR stop. Match the backtest so the push never
# suggests a stop the strategy doesn't actually use.
SL_MULT = ATR_SL_MULT if STRATEGY == "trend" else 0.0
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

WINDOW = {"meanrev": ("12y", "1d"), "bb": ("12y", "1d"), "trend": ("730d", "1h")}
EMOJI = {"BUY": "\U0001F7E2", "SELL/EXIT": "\U0001F534", "HOLD": "⚪"}
# ntfy renders these tag names as emoji icons. ASCII-safe for HTTP headers.
TAGS = {"BUY": "green_circle", "SELL/EXIT": "red_circle", "HOLD": "white_circle"}
# Plain-English action so "SELL/EXIT" can't be misread as "go short".
PHRASE = {"BUY": "BUY", "SELL/EXIT": "EXIT (close long)", "HOLD": "HOLD"}
# The tradeable ETF prices at ~1/10 of its index, which confuses ("SPY 756" vs
# "S&P 500 7,565"). Show the real index level alongside so they line up.
INDEX_FOR = {
    "SPY": ("^GSPC", "S&P 500"), "QQQ": ("^NDX", "Nasdaq-100"),
    "DIA": ("^DJI", "Dow"), "IWM": ("^RUT", "Russell 2000"),
}


def index_context(sym: str) -> str:
    """' · S&P 500 ≈ 7,565' for an ETF whose underlying index we know, else ''.
    Best-effort: a failed fetch must never block the alert."""
    mapping = INDEX_FOR.get(sym.upper())
    if not mapping:
        return ""
    ticker, label = mapping
    try:
        level = float(fetch(ticker, "5d", "1d")["Close"].iloc[-1])
        return f"  ·  {label} ≈ {level:,.0f}"
    except Exception:
        return "  ·  ETF priced at ~1/10 of its index"


def near_us_close() -> bool:
    """True on a weekday within ~15:25-16:05 ET. Auto-handles DST when the cron
    is scheduled at both candidate UTC times — only the right one lands here."""
    now = datetime.now(ET)
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and (15 * 60 + 25) <= minutes <= (16 * 60 + 5)


def push(title: str, body: str, tags: str = "chart_with_upwards_trend") -> None:
    if not NTFY_TOPIC:
        print(f"[dry-run: no NTFY_TOPIC] would push:\n  {title}\n{body}")
        return
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        method="POST",
        headers={"Title": title, "Priority": "high", "Tags": tags},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"pushed ({resp.status}) to topic {NTFY_TOPIC}")


def push_orb_plan() -> None:
    """Funded mode: push today's Opening Range Breakout PLAN + risk guardrails.
    Framed as a disciplined plan, NOT a predicted winner (ORB has no proven edge —
    see FUNDED.md). Schedule the cron ~30min after the US open so the range exists."""
    from orb import ACCOUNT, RISK_PCT, backtest_orb
    _, plan = backtest_orb(fetch("SPY", "60d", "15m"))
    if not plan or not plan["range"]:
        print("No ORB plan available yet (range not formed).")
        return
    shares = (ACCOUNT * RISK_PCT / 100.0) / plan["range"]
    lines = [f"📋 SPY ORB plan — {plan['date']}  ·  S&P 500 ETF",
             f"opening range {plan['or_low']}–{plan['or_high']} (={plan['range']})"]
    if plan["long_ok"]:
        lines.append(f"🟢 LONG stop-buy >{plan['or_high']} · stop {plan['or_low']} · tgt {plan['long_target']}")
    if plan["short_ok"]:
        lines.append(f"🔴 SHORT stop-sell <{plan['or_low']} · stop {plan['or_high']} · tgt {plan['short_target']}")
    lines += [f"size 1% risk ≈ {shares:.0f} SPY shares  ·  FLAT by close (no overnight)",
              "rules: ≤3 trades, stop ALWAYS, don't rush the target",
              "⚠️ a PLAN not a prediction · ORB has no proven edge · paper/funded · not advice"]
    push(f"SPY ORB plan {plan['date']}", "\n".join(lines), tags="clipboard")


def main() -> None:
    force = "--force" in sys.argv
    brief = "--brief" in sys.argv
    if STRATEGY == "orb":          # funded mode: daily plan, own cron timing
        push_orb_plan()
        return
    if not force and not near_us_close():
        print("Not in the US-close window; skipping (use --force to test).")
        return

    period, interval = WINDOW.get(STRATEGY, WINDOW["meanrev"])
    sigs = [(sym, live_signal(fetch(sym, period, interval),
                              strategy=STRATEGY, sl_mult=SL_MULT))
            for sym in SYMBOLS]
    actionable = any(s.action != "HOLD" for _, s in sigs)
    events = high_impact_events(datetime.now(ET).date())

    # Short, scannable body: one line per symbol, optional event flag + 1 headline.
    lines = []
    for sym, s in sigs:
        line = (f"{EMOJI.get(s.action, '')} {PHRASE.get(s.action, s.action)} — "
                f"{sym} ${s.price}{index_context(sym)}")
        if s.suggested_stop is not None:
            line += f"  · stop {s.suggested_stop}"   # only the trend strategy sets one
        lines.append(line)
        # How to act in a paper account (TradingView etc.): mean reversion has no
        # price SL/TP — exit is the next SELL signal or the time stop.
        if s.action == "BUY" and STRATEGY != "trend":
            lines.append("   → buy · no SL/TP · exit on my SELL alert (RSI2>75) or ~10 trading days")
        elif s.action == "SELL/EXIT":
            lines.append("   → close the long now (take-profit, not a short)")
    if events:
        lines.append("⚠️ " + events[0] + " — expect whipsaw")
    heads = fetch_headlines(SYMBOLS, limit=1)
    if heads:
        lines.append("\U0001F4F0 " + heads[0])
    lines.append("not advice · paper only")
    body = "\n".join(lines)

    if len(sigs) == 1:
        sym, s = sigs[0]
        title = f"{sym} {PHRASE.get(s.action, s.action)}"   # plain text (HTTP header = latin-1)
        tags = TAGS.get(s.action, "chart_with_upwards_trend")
    else:
        title = "Morning brief" if brief else "Signals"
        tags = "chart_with_upwards_trend"

    # Push on an actionable signal, on a brief, OR when a high-impact event lands.
    if actionable or brief or events:
        push(title, body, tags)
    else:
        print("All HOLD — no push.\n" + body)


def _alert_failure(exc: BaseException) -> None:
    """Best-effort phone alert when the job itself breaks, so silence is never
    mistaken for 'all HOLD'. If the failure is the network, this push may also
    fail — nothing we can do, but every non-network failure still reaches you."""
    detail = f"{type(exc).__name__}: {exc}"[:300]
    try:
        push("⚠️ trade-signals FAILED",
             f"The signal job errored — you may be flying blind.\n{detail}\n"
             f"Check the GitHub Actions logs.", tags="warning")
    except Exception as push_exc:   # noqa: BLE001 - last-resort, must not raise
        print(f"failure-alert push also failed: {push_exc}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):   # real failure (e.g. data.fetch gave up)
            _alert_failure(exc)
        raise
    except Exception as exc:            # noqa: BLE001 - top-level guard for a cron
        import traceback
        traceback.print_exc()
        _alert_failure(exc)
        sys.exit(1)
