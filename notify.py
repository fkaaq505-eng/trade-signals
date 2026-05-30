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
AST = ZoneInfo("Asia/Riyadh")   # user is in Saudi Arabia; show local times too
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
# Paper position sizing (no stop -> size by % of account). Override via env.
PAPER_ACCOUNT = float(os.environ.get("PAPER_ACCOUNT", "10000"))   # paper account size, $
ALLOC_PCT = float(os.environ.get("ALLOC_PCT", "20"))             # % of account per BUY

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


def _index_ratio(sym: str, etf_price: float) -> tuple[float, str]:
    """(ratio, label) to convert ETF prices into index points — e.g. SPY ~756 ->
    S&P 500 ~7,560. Best-effort: a failed fetch falls back to SPY's ~10x ratio so the
    alert still shows sensible 'thousands' levels rather than breaking."""
    mapping = INDEX_FOR.get(sym.upper())
    if not mapping or etf_price <= 0:
        return 1.0, sym.upper()
    ticker, label = mapping
    try:
        level = float(fetch(ticker, "5d", "1d")["Close"].iloc[-1])
        return level / etf_price, label
    except Exception:
        return 10.0, label   # SPY trades ~1/10 of the S&P 500; safe fallback


def near_us_close() -> bool:
    """True on a weekday within ~15:25-16:05 ET. Auto-handles DST when the cron
    is scheduled at both candidate UTC times — only the right one lands here."""
    now = datetime.now(ET)
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and (15 * 60 + 25) <= minutes <= (16 * 60 + 5)


def near_us_open() -> bool:
    """True on a weekday within ~9:55-10:45 ET — just after the 30-min opening range
    forms, the start of ORB's prime session. Dual UTC crons (DST) → only the in-season
    one lands here; the other fires at 9:00 or 11:00 ET and is skipped, so ORB pushes
    exactly once per trading day."""
    now = datetime.now(ET)
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and (9 * 60 + 55) <= minutes <= (10 * 60 + 45)


def _et_ast(date_str: str, hh: int, mm: int) -> str:
    """'09:30 ET / 16:30 AST' for an ET wall-clock time on the plan date. Saudi has
    no DST; the US side shifts, and zoneinfo handles the offset for that date."""
    et = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hh, minute=mm, tzinfo=ET)
    return f"{hh:02d}:{mm:02d} ET / {et.astimezone(AST):%H:%M} AST"


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
    see FUNDED.md). Fires ~30min after the US open (near_us_open) so the range exists.
    Levels are shown in S&P 500 index points (the 'thousands' an ES/MES funded trader
    watches), with the SPY ETF price in brackets."""
    from orb import ACCOUNT, RISK_PCT, RR, backtest_orb
    df = fetch("SPY", "60d", "15m")
    _, plan = backtest_orb(df)
    if not plan or not plan["range"]:
        print("No ORB plan available yet (range not formed).")
        return
    spy_last = float(df["Close"].iloc[-1])
    ratio, label = _index_ratio("SPY", spy_last)

    def sp(price: float) -> str:               # SPY price -> index points, e.g. 7,579
        return f"{price * ratio:,.0f}"

    risk_usd = ACCOUNT * RISK_PCT / 100.0
    shares = risk_usd / plan["range"]
    close_ast = _et_ast(plan["date"], 15, 55).split(" / ")[1]   # just '22:55 AST'

    lines = [
        f"📋 SPY day-trade — {plan['date']} ({label}) · paper, not advice",
        f"{label} now ≈ {spy_last * ratio:,.0f}",
    ]

    def block(emoji: str, action: str, entry: float, stop: float, target: float) -> list[str]:
        direction = "above" if action == "BUY" else "below"
        return [
            f"{emoji} {action} if it breaks {direction} {sp(entry)}  (SPY {entry})",
            f"   safety exit: {sp(stop)}  (SPY {stop})",
            f"   take profit: {sp(target)}  (SPY {target})",
            f"   ~{shares:.0f} SPY shares (${risk_usd:,.0f} risk) · close by {close_ast}",
        ]

    if plan["long_ok"]:
        lines += block("🟢", "BUY", plan["or_high"], plan["or_low"], plan["long_target"])
    if plan["short_ok"]:
        lines += block("🔴", "SELL/short", plan["or_low"], plan["or_high"], plan["short_target"])

    lines += [
        "No breakout = no trade. Set as ONE broker order — it runs without you.",
        "⚠️ no proven edge · paper only · you place it, not me",
    ]
    push(f"SPY ORB plan {plan['date']}", "\n".join(lines), tags="clipboard")


def push_funded_plan() -> None:
    """FUNDED mode: push today's disciplined eval session plan + live progress.
    Discipline IS the edge (no entry edge exists — see FUNDED_EVAL.md). Reads the
    private funded_state.json if present for live equity/buffer/days; otherwise shows
    the firm's rules + sizing guidance. Reminds: which market, how often, flat by close."""
    import os as _os
    try:
        import funded_forward as ff
    except Exception as exc:                       # never let an import break the cron
        push("Funded plan", f"could not load funded_forward: {exc}", tags="warning")
        return
    firm_key = _os.environ.get("FUNDED_FIRM", ff.DEFAULT_FIRM)
    cfg = ff.FIRMS.get(firm_key, ff.FIRMS[ff.DEFAULT_FIRM])
    acct = float(_os.environ.get("FUNDED_ACCOUNT", "50000"))
    market = _os.environ.get("FUNDED_MARKET", "MES micro S&P (or MNQ for momentum)")
    target = acct * cfg.profit_target_pct / 100.0
    buffer = acct * cfg.trailing_dd_pct / 100.0
    daily = acct * cfg.daily_loss_limit_pct / 100.0
    close_ast = _et_ast(datetime.now(ET).date().isoformat(), 15, 55).split(" / ")[1]

    lines = [f"📋 Funded eval plan — {cfg.name}", f"market: {market} · US session, flat by {close_ast}"]
    state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ff.STATE_FILE)
    if os.path.exists(state_path):                 # live progress if a paper attempt is running
        try:
            from risk_engine import status_summary
            s = status_summary(ff.load_state(state_path, firm_key, acct))
            if s["eval_passed"]:
                lines.append("✅ PASSED — stop, bank it.")
            elif s["eval_failed"]:
                lines.append(f"❌ FAILED — {s['failure_reason'][:80]} · reset for a fresh attempt")
            else:
                lines += [
                    f"equity ${s['current_equity']:,.0f} · ${target - s['cumulative_profit']:,.0f} to target",
                    f"DD buffer ${s['trailing_dd_buffer_remaining']:,.0f} · {s['days_remaining']}d left"
                    f"{' · ⛔LOCKED' if s['daily_locked_out'] else ''}",
                ]
        except Exception as exc:                   # corrupt/old state must not break the push
            lines.append(f"(state unreadable: {exc})")
    else:
        lines.append(f"target +${target:,.0f} · DD buffer ${buffer:,.0f} · daily-loss ${daily:,.0f}")

    lines += [
        f"RULES: risk ~0.5-1%/trade · max {cfg.max_trades_per_day} trades/day · NEVER oversize",
        "~1-3 trades/day, only the clean US-open hours. No setup = no trade.",
        "Log every paper trade: funded_forward.py · ⚠️ paper, no edge, discipline is the job",
    ]
    push(f"Funded plan {datetime.now(ET).date()}", "\n".join(lines), tags="clipboard")


def push_tjr_plan() -> None:
    """MAIN funded method: push today's TJR session-liquidity + FVG plan, funded-sized.
    TJR has NO validated edge (HANDOFF 16/19-20) — it is a funded-LEGAL, disciplined way
    to take the trade and ride the eval's variance. Levels from free Yahoo NQ=F/ES=F."""
    import os as _os
    try:
        from tjr_funded import build_plan
        symbol = _os.environ.get("FUNDED_SYMBOL", "MNQ")
        acct = float(_os.environ.get("FUNDED_ACCOUNT", "50000"))
        risk = float(_os.environ.get("FUNDED_RISK_PCT", "0.75"))
        p = build_plan(symbol, acct, risk)
    except Exception as exc:                       # never break the cron on a data hiccup
        push("TJR plan", f"could not build TJR plan: {exc}", tags="warning")
        return
    flat_ast = p["flat_by"].split(" / ")[1]
    lines = [
        f"📋 TJR plan {p['symbol']} — paper, no proven edge, discipline play",
        f"pools ({p['prior_day']}): PDH {p['pdh']} · PDL {p['pdl']} · now {p['last']}",
        f"size {p['contracts']} {p['symbol']} = ${p['risk_dollars']:,.0f} risk · stop {p['stop_pts']}pts · R:R ~{p['rr']}:1",
        f"🔴 raid ABOVE {p['pdh']} + bearish FVG → SHORT, stop {p['short']['stop']}, target {p['pdl']}",
        f"🟢 raid BELOW {p['pdl']} + bullish FVG → LONG, stop {p['long']['stop']}, target {p['pdh']}",
        f"one setup/day · NO raid+FVG = NO trade · flat by {flat_ast}",
        "⚠️ no edge — funded-legal discipline only. Log it: journal.py",
    ]
    push(f"TJR plan {p['symbol']} {datetime.now(ET).date()}", "\n".join(lines), tags="clipboard")


def main() -> None:
    force = "--force" in sys.argv
    brief = "--brief" in sys.argv
    if STRATEGY == "tjr":           # MAIN funded method: TJR session-liquidity plan
        push_tjr_plan()
        return
    if STRATEGY == "funded":        # funded eval discipline plan + progress (own cron)
        push_funded_plan()
        return
    if STRATEGY == "orb":          # funded mode: ORB plan at the open (own cron)
        if force or near_us_open():
            push_orb_plan()
        else:
            print("Not in the US-open window; skipping (use --force to test).")
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

    # Body shows ONLY the markets to ACT on (BUY/EXIT). HOLDs are hidden so the
    # message is just "what to trade". Each BUY shows how many units to buy.
    actionable_sigs = [(sym, s) for sym, s in sigs if s.action != "HOLD"]
    lines = []
    if not actionable_sigs:
        lines.append("✅ All HOLD — nothing to trade today.")
    for sym, s in actionable_sigs:
        lines.append(f"{EMOJI.get(s.action, '')} {PHRASE.get(s.action, s.action)} — "
                     f"{sym} ${s.price}{index_context(sym)}")
        if s.action == "BUY" and STRATEGY != "trend":
            units = int(PAPER_ACCOUNT * ALLOC_PCT / 100.0 / s.price) if s.price > 0 else 0
            lines.append(f"   → BUY ~{units} units (~{ALLOC_PCT:.0f}% of ${PAPER_ACCOUNT:,.0f}) · "
                         f"no SL/TP · sell on my EXIT alert")
        elif s.action == "SELL/EXIT":
            lines.append("   → SELL all your units now (take-profit, not a short)")
    if events:
        lines.append("⚠️ " + events[0] + " — expect whipsaw")
    heads = fetch_headlines(SYMBOLS, limit=1)
    if heads:
        lines.append("\U0001F4F0 " + heads[0])
    lines.append("not advice · paper only")
    body = "\n".join(lines)

    n_act = len(actionable_sigs)
    if len(sigs) == 1:
        sym, s = sigs[0]
        title = f"{sym} {PHRASE.get(s.action, s.action)}"   # plain text (HTTP header = latin-1)
        tags = TAGS.get(s.action, "chart_with_upwards_trend")
    else:
        title = f"{n_act} to trade" if n_act else "All HOLD — nothing to do"
        tags = "green_circle" if n_act else "white_circle"

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
