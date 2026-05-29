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
from news import news_block

ET = ZoneInfo("America/New_York")
AST = ZoneInfo("Asia/Riyadh")   # user is in Saudi Arabia (UTC+3, no DST)
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
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

WINDOW = {"meanrev": ("12y", "1d"), "trend": ("730d", "1h")}


def near_us_close() -> bool:
    """True on a weekday within ~15:25-16:05 ET. Auto-handles DST when the cron
    is scheduled at both candidate UTC times — only the right one lands here."""
    now = datetime.now(ET)
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and (15 * 60 + 25) <= minutes <= (16 * 60 + 5)


def push(title: str, body: str) -> None:
    if not NTFY_TOPIC:
        print(f"[dry-run: no NTFY_TOPIC] would push:\n  {title}\n{body}")
        return
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        method="POST",
        headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"pushed ({resp.status}) to topic {NTFY_TOPIC}")


def main() -> None:
    force = "--force" in sys.argv
    brief = "--brief" in sys.argv
    if not force and not near_us_close():
        print("Not in the US-close window; skipping (use --force to test).")
        return

    period, interval = WINDOW.get(STRATEGY, WINDOW["meanrev"])
    lines, actionable = [], False
    for sym in SYMBOLS:
        sig = live_signal(fetch(sym, period, interval), strategy=STRATEGY)
        flag = "" if sig.action == "HOLD" else "   <<< ACT"
        line = f"{sym}: {sig.action} @ {sig.price} (rsi {sig.rsi})"
        if sig.suggested_stop is not None:
            line += f"  stop {sig.suggested_stop}"
        lines.append(line + flag)
        actionable = actionable or sig.action != "HOLD"

    now_ast = datetime.now(AST).strftime("%a %d %b %H:%M AST")
    footer = ("\n" + now_ast +
              "\nUS close 16:00 ET = 23:00 AST (summer) / 00:00 (winter)."
              "\nPrefer daytime? Act at next US open ~16:30/17:30 AST, same signal."
              "\nRules-based, not advice. You decide. Paper first.")

    body = "\n".join(lines)
    nb = news_block(SYMBOLS, datetime.now(ET).date())  # fresh news + event flag each run
    if nb:
        body += "\n\n" + nb
    body += footer

    # Push on an actionable signal, on a brief, OR when a high-impact event lands.
    has_event = "HIGH-IMPACT TODAY" in nb
    if actionable or brief or has_event:
        title = "Morning brief" if brief else "Trade signal"
        push(f"{title} ({STRATEGY})", body)
    else:
        print("All HOLD — no push.\n" + body)


if __name__ == "__main__":
    main()
