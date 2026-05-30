"""
Monte Carlo prop-EVALUATION simulator — the honest "highest chance to pass" tool.

There is NO validated trading edge on accessible free data (HANDOFF items 7-19:
ORB/RSI2/VWAP/FVG/sweep all lose OOS after fees on SPY/QQQ/NQ/ES/BTC/ETH). So this
tool does NOT pretend to find money. It answers the only question still mathematically
optimizable:

    "Given a roughly break-even (slightly negative after fees) strategy, what choices
     MAXIMISE the probability of passing a funded evaluation — and what IS that
     probability, honestly?"

The eval is a finite game: reach a PROFIT TARGET before hitting a DRAWDOWN floor,
within a day limit, respecting daily-loss / consistency / min-day rules. Pass
probability is driven by LEVERS you control, not a magic signal:

  1. BARRIER RATIO = buffer/(buffer+target) is the CEILING. With no edge, NO sizing trick
     pushes P(pass) above it (gambler's ruin). Pick the firm with the highest ratio — the
     biggest drawdown buffer relative to the profit target.
  2. DRAWDOWN TYPE sets how close you get to that ceiling: static reaches it; "lock"
     (trails, then freezes once you're ahead) is close; EOD-trailing a little less;
     intraday-trailing worst (unrealized gains pull the floor up). Consistency / daily-loss
     / min-day rules pull you further below the ceiling.
  3. BET SIZING moves you toward the ceiling; it cannot beat it. Too TIMID is strictly
     worst — the negative drift + day limit grind you out. Moderate-to-bold all approach
     the ceiling; sizing past "clear the target in ~1-3 trades" just turns the eval into a
     single coin-flip at your win-rate (max variance, same ceiling).
  4. PAYOFF SKEW: at equal expectancy, under a trailing floor a smoother / higher-win curve
     reaches the ceiling more reliably than lottery skew (whose losing streaks breach first).
  5. ATTEMPTS: P(>=1 pass in k) = 1-(1-p)^k. Cheap resets are the sane way to raise
     cumulative odds — buy the math, not one hero attempt.

HONEST TRUTH: maximising P(pass) is NOT making money. A break-even strategy passes by
VARIANCE; the funded account afterward is a separate, harder hurdle; expected $ value is
negative (eval fees + no edge). Documented real pass rates are ~5-20% first-attempt and
only ~7% ever get a payout (FPFX 300k-account study) — LOWER than this sim's disciplined
numbers, because real traders oversize, revenge-trade and carry a worse-than-break-even
edge. Treat the sim's output as the DISCIPLINED CEILING for someone who actually uses
risk_engine.py, not a promise. Firm rules verified May 2026; re-verify before paying.

    python eval_montecarlo.py
    python eval_montecarlo.py --trials 50000
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace

import numpy as np

ADVERSE_HEAT_R = 0.5      # a winner still dips ~0.5R underwater first (intraday breach check)
DEFAULT_TRIALS = 20_000
RNG_SEED = 12345
NO_LIMIT_DAYS = 200       # practical cap when a firm has "no max days"


@dataclass(frozen=True)
class EvalFirm:
    """A funded-eval rule set (50k plan). Numbers researched May 2026 — VERIFY on the
    firm's live dashboard before paying; rules change often (Apex 4.0, Alpha May-2026)."""
    name: str
    dd_pct: float                 # drawdown buffer, % of account
    target_pct: float             # profit target, % of account
    daily_loss_pct: float         # 0 = none. Modelled as a disciplined day-STOP, not a fail.
    mode: str                     # "static" | "eod" | "intraday" | "lock"
    lock_floor_offset_pct: float  # for mode="lock": floor freezes here (% above start). 0=start.
    consistency_ratio: float      # 0 = none; else no single day > ratio * total profit
    min_days: int
    max_days: int                 # 0 -> NO_LIMIT_DAYS
    eval_fee: float               # incl. activation where one-time, for the $-cost math
    reset_fee: float


# --- Researched 50k presets (May 2026). Sources in FUNDED_EVAL.md / research handoff. ---
ALPHA_ZERO = EvalFirm(            # #1 structural: EOD-lock at start, no consistency, soft DLL
    "Alpha Futures Zero 50k (EOD-lock@start, no consistency)",
    dd_pct=4.0, target_pct=6.0, daily_loss_pct=2.0, mode="lock",
    lock_floor_offset_pct=0.0, consistency_ratio=0.0, min_days=1, max_days=0,
    eval_fee=119.0, reset_fee=119.0)

APEX_EOD = EvalFirm(              # #2: EOD-lock@+$100, no consistency, 30-day cap, cheap promo
    "Apex 4.0 EOD 50k (lock@+$100, 30-day cap)",
    dd_pct=4.0, target_pct=6.0, daily_loss_pct=2.0, mode="lock",
    lock_floor_offset_pct=0.2, consistency_ratio=0.0, min_days=1, max_days=30,
    eval_fee=119.0, reset_fee=20.0)   # ~$20 eval promo + $99 activation amortised

TOPSTEP = EvalFirm(               # #1 for PASS x PAYOUT: EOD-trail both stages, clean payouts
    "Topstep 50k (EOD-trail, Standard path: no consistency)",
    dd_pct=4.0, target_pct=6.0, daily_loss_pct=2.0, mode="eod",
    lock_floor_offset_pct=0.0, consistency_ratio=0.0, min_days=2, max_days=0,
    eval_fee=49.0, reset_fee=49.0)

ELITE_STATIC = EvalFirm(          # true STATIC floor, but worse ratio (target 8%)
    "Elite Trader Funding 50k STATIC (floor never moves, target $4k)",
    dd_pct=4.0, target_pct=8.0, daily_loss_pct=0.0, mode="static",
    lock_floor_offset_pct=0.0, consistency_ratio=0.0, min_days=5, max_days=0,
    eval_fee=449.0, reset_fee=449.0)

BULENOX_INTRA = EvalFirm(         # intraday-trail BUT big $2,500 buffer (ratio 0.83)
    "Bulenox 50k Opt.1 (intraday-trail, big $2.5k buffer)",
    dd_pct=5.0, target_pct=6.0, daily_loss_pct=0.0, mode="intraday",
    lock_floor_offset_pct=0.0, consistency_ratio=0.0, min_days=0, max_days=0,
    eval_fee=87.0, reset_fee=78.0)

ALL_FIRMS = [ALPHA_ZERO, APEX_EOD, TOPSTEP, BULENOX_INTRA, ELITE_STATIC]


@dataclass(frozen=True)
class SimParams:
    expectancy_r: float = -0.02   # net R/trade AFTER fees. ~0 to slightly negative = reality.
    win_r: float = 2.0            # winner pays +win_r R; loser -1R (skew knob)
    risk_pct: float = 1.0         # $ risked per trade as % of starting account
    trades_per_day: int = 2
    account: float = 50_000.0


def win_rate_for(expectancy_r: float, win_r: float) -> float:
    """E = p*win_r - (1-p)  ->  p = (E+1)/(win_r+1)."""
    p = (expectancy_r + 1.0) / (win_r + 1.0)
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"impossible win_rate {p:.3f} for E={expectancy_r}, win_r={win_r}")
    return p


def draw_r(rng: np.random.Generator, p_win: float, win_r: float) -> float:
    return win_r if rng.random() < p_win else -1.0


def simulate_attempt(rng: np.random.Generator, firm: EvalFirm, sim: SimParams) -> str:
    """One eval attempt -> 'pass' | 'dd' | 'timeout'. Disciplined trader: a day that hits
    the daily-loss limit STOPS for the day (risk_engine behaviour), it does not auto-fail."""
    acct = sim.account
    risk_d = acct * sim.risk_pct / 100.0
    dd = acct * firm.dd_pct / 100.0
    daily_limit = acct * firm.daily_loss_pct / 100.0 if firm.daily_loss_pct else None
    target_equity = acct * (1.0 + firm.target_pct / 100.0)
    lock_floor = acct * (1.0 + firm.lock_floor_offset_pct / 100.0)
    p_win = win_rate_for(sim.expectancy_r, sim.win_r)
    max_days = firm.max_days or NO_LIMIT_DAYS

    equity = acct
    floor = acct - dd                 # static starting floor
    locked = firm.mode == "static"
    day_profits: list[float] = []

    for _ in range(max_days):
        day_start = equity
        for _ in range(sim.trades_per_day):
            r = draw_r(rng, p_win, sim.win_r)
            trade_low = equity + risk_d * (r if r < 0 else -ADVERSE_HEAT_R)
            if trade_low < floor:
                return "dd"
            equity += risk_d * r
            if firm.mode == "intraday" and not locked:
                floor = max(floor, equity - dd)     # ratchets continuously
            if daily_limit is not None and equity - day_start <= -daily_limit:
                break                                # disciplined day-stop
        # end of day: eod / lock floors ratchet here
        if not locked and firm.mode in ("eod", "lock"):
            new_floor = equity - dd
            if firm.mode == "lock" and new_floor >= lock_floor:
                floor, locked = lock_floor, True     # freeze forever once far enough ahead
            else:
                floor = max(floor, new_floor)
        day_profits.append(equity - day_start)
        if equity >= target_equity and len(day_profits) >= max(1, firm.min_days):
            total = equity - acct
            if firm.consistency_ratio <= 0.0 or (
                    total > 0 and max(day_profits) <= firm.consistency_ratio * total):
                return "pass"
            # target hit but consistency unmet -> keep trading to balance the days
    return "timeout"


def monte_carlo(firm: EvalFirm, sim: SimParams, trials: int, seed: int = RNG_SEED) -> dict:
    rng = np.random.default_rng(seed)
    counts = {"pass": 0, "dd": 0, "timeout": 0}
    for _ in range(trials):
        counts[simulate_attempt(rng, firm, sim)] += 1
    return {k: v / trials for k, v in counts.items()}


def barrier_ratio(firm: EvalFirm) -> float:
    return firm.dd_pct / (firm.dd_pct + firm.target_pct)


def p_at_least_one(p: float, k: int) -> float:
    return 1.0 - (1.0 - p) ** k


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _hdr(t: str) -> None:
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


def demo_levers(trials: int) -> None:
    _hdr("LEVER 1+2 — the barrier ratio is the CEILING; DD-type & rules pull you below it")
    base = SimParams(expectancy_r=0.0, win_r=1.0, risk_pct=2.0, trades_per_day=2)
    print(f"{'firm':<50}{'mode':>9}{'barrier':>8}{'P(pass)':>9}")
    print("-" * 76)
    for firm in sorted(ALL_FIRMS, key=barrier_ratio, reverse=True):
        print(f"{firm.name[:48]:<50}{firm.mode:>9}{barrier_ratio(firm):>8.0%}"
              f"{monte_carlo(firm, base, trials)['pass']:>9.1%}")
    print("  -> P(pass) is capped by the barrier ratio (gambler's ruin). Bulenox's big buffer")
    print("     gives the highest ceiling; Topstep's intraday-trail + 50% consistency and")
    print("     Elite's 8% target knock theirs down. No edge can beat the ratio — only firm choice lifts it.")

    _hdr("LEVER 3 — sizing reaches the ceiling, can't beat it (E=-0.03R, win_r=1, Alpha)")
    print(f"{'risk %/trade':<16}{'P(pass)':>10}{'regime':>26}")
    print("-" * 52)
    notes = {0.25: "too timid -> grinds/times out", 2.0: "approaches the ceiling",
             8.0: "~one coin-flip at win-rate"}
    for risk in (0.25, 0.5, 1.0, 2.0, 4.0, 8.0):
        r = monte_carlo(ALPHA_ZERO, SimParams(-0.03, 1.0, risk, 2), trials)
        print(f"{risk:<16.2f}{r['pass']:>10.1%}{notes.get(risk, ''):>26}")
    print(f"  -> timid is strictly worst. Bigger sizing climbs toward this firm's effective")
    print(f"     ceiling (here ~31%, below the {barrier_ratio(ALPHA_ZERO):.0%} barrier because the lock trails")
    print(f"     until you're ahead); the extreme is just a single coin-flip at your win-rate.")

    _hdr("LEVER 4 — payoff SKEW at EQUAL expectancy (E=-0.03R, risk 1%) — by firm")
    print(f"{'style':<20}{'win_r':>7}{'win%':>7}{'ALPHA(eod)':>11}{'BULENOX(intra)':>15}")
    print("-" * 60)
    for win_r, name in ((0.4, "high win/small R"), (1.0, "symmetric"),
                        (2.0, "positive skew"), (4.0, "lottery skew")):
        p = win_rate_for(-0.03, win_r)
        ra = monte_carlo(ALPHA_ZERO, SimParams(-0.03, win_r, 1.0, 2), trials)["pass"]
        rb = monte_carlo(BULENOX_INTRA, SimParams(-0.03, win_r, 1.0, 2), trials)["pass"]
        print(f"{name:<20}{win_r:>7.1f}{p:>7.0%}{ra:>11.1%}{rb:>15.1%}")
    print("  -> best skew is NOT universal: at small 1% size more skew helps (tiny losses, deep")
    print("     buffer); at larger size it flips (long streaks breach the floor first). Skew x")
    print("     size x DD-type interact, so the optimiser searches them jointly. No rule of thumb.")


def optimize(firm: EvalFirm, trials: int) -> tuple[SimParams, dict]:
    best_p, best_s, best_r = -1.0, None, None
    for risk in (0.25, 0.5, 1.0, 1.5, 2.0, 3.0):
        for win_r in (1.0, 1.5, 2.0, 3.0):
            for tpd in (1, 2, 3):
                s = SimParams(-0.03, win_r, risk, tpd)
                r = monte_carlo(firm, s, trials)
                if r["pass"] > best_p:
                    best_p, best_s, best_r = r["pass"], s, r
    return best_s, best_r


def report(trials: int) -> None:
    _hdr("OPTIMISER — best achievable P(pass) per firm at E=-0.03R (vs the barrier ceiling)")
    print(f"{'firm':<50}{'barrier':>8}{'P(pass)':>9}{'risk%':>7}{'win_r':>7}{'eval$':>7}")
    print("-" * 88)
    rows = []
    for firm in sorted(ALL_FIRMS, key=barrier_ratio, reverse=True):
        s, r = optimize(firm, trials)
        rows.append((firm, s, r))
        print(f"{firm.name[:48]:<50}{barrier_ratio(firm):>8.0%}{r['pass']:>9.1%}"
              f"{s.risk_pct:>7.2f}{s.win_r:>7.1f}{firm.eval_fee:>7.0f}")
    print("  -> best achievable ~ tracks the barrier ratio. You can't optimise above the ceiling;")
    print("     you can only pick a firm with a higher one and size well enough to reach it.")

    firm, s, r = max(rows, key=lambda x: x[2]["pass"])
    p = r["pass"]
    _hdr("RECOMMENDATION + MULTI-ATTEMPT (the realistic 'whatever it takes' path)")
    print(f"Highest pass-ODDS firm: {firm.name}  (barrier {barrier_ratio(firm):.0%})")
    print(f"  P(pass)/attempt ~= {p:.1%}  (fail: DD {r['dd']:.0%}, timeout {r['timeout']:.0%})")
    print("  ⚠️ PASS-ODDS != GET-PAID. Bulenox has a documented undocumented 'flip-day' rule that")
    print("     has denied rule-compliant payouts. For pass AND a verified payout, use TOPSTEP")
    print("     (EOD both stages, cleanest payouts) or Apex (automated). See FUNDED_EVAL.md.")
    print(f"  sizing at the max: {s.risk_pct:.2f}% risk/trade, win_r={s.win_r:.1f}, "
          f"{s.trades_per_day} trade(s)/day")
    print("  (note: the max-P(pass) sizing is high-variance — it clears the target in a few")
    print("   trades, ~a coin-flip at your win-rate. That IS the math-best for a no-edge eval.)\n")
    print(f"{'attempts':<10}{'P(>=1 pass)':>13}{'~eval $ spent':>15}")
    print("-" * 38)
    for k in (1, 2, 3, 5, 8):
        spent = firm.eval_fee + (k - 1) * firm.reset_fee
        print(f"{k:<10}{p_at_least_one(p, k):>13.1%}{spent:>15,.0f}")
    print(f"\n  Expected attempts to first pass ~= {1.0 / p:.1f}  "
          f"(~${firm.eval_fee + (1.0 / p - 1) * firm.reset_fee:,.0f} in eval fees).")

    _hdr("EDGE SENSITIVITY — does a small REAL edge matter? (best firm + sizing)")
    print(f"{'net edge R/trade':<18}{'P(pass)':>10}")
    print("-" * 28)
    for e in (-0.05, -0.03, 0.0, 0.03, 0.05, 0.10):
        print(f"{e:<+18.2f}{monte_carlo(firm, replace(s, expectancy_r=e), trials)['pass']:>10.1%}")
    print("  -> a small edge helps modestly; firm + sizing dominate at the eval stage.")


def honest_footer() -> None:
    _hdr("THE HONEST BOTTOM LINE")
    print("""  - This MAXIMISES P(pass); it does NOT create profit. With no edge every pass is
    variance and expected $ value is NEGATIVE (eval fees + no edge).
  - Reality check: documented first-attempt pass rates are ~5-20% and only ~7% ever get
    a payout. This sim's higher numbers assume IRON discipline (moderate sizing, day-stop
    lockouts, no revenge trades) — i.e. they are a CEILING you only reach by actually
    enforcing the rules with risk_engine.py. Undisciplined trading collapses to the 5-20%.
  - Recipe the sim supports: (1) BARRIER RATIO is the ceiling — pick the firm with the
    biggest buffer/target (Bulenox 0.45 > the 0.40 crowd > Elite 0.33). (2) Then pick a
    forgiving DD type to actually reach it: EOD-lock (Alpha/Apex) or static > intraday;
    avoid Topstep's intraday-trail + 50% consistency. (3) Reach the LOCK point (~+$2,100)
    fast on lock-plans, then the floor freezes and the rest is cash-only. (4) Don't trade
    timid (you grind out); size to reach target in a few trades; smoother/higher-win beats
    lottery skew under a trailing floor. (5) Buy SEVERAL cheap-reset attempts (Apex ~$20
    promo) — compounding 1-(1-p)^k is the only honest way to push cumulative odds up.
  - Passing the EVAL is the easy hurdle. KEEPING the funded account (intraday DD on the
    PA, payout ladder, no edge) is the hard one — most who pass still bleed it out.
  - Forward paper-test with journal.py and ENFORCE sizing with risk_engine.py BEFORE you
    risk a real eval fee. Re-verify every firm number on its live rulebook first.""")


def main() -> None:
    ap = argparse.ArgumentParser(description="Monte Carlo funded-eval pass-probability tool.")
    ap.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    args = ap.parse_args()
    print("\nFUNDED-EVAL MONTE CARLO — maximising P(pass) honestly (no edge assumed).")
    print(f"trials/config = {args.trials:,}  |  assumed net edge = -0.03R/trade (fees, no signal)")
    demo_levers(args.trials)
    report(args.trials)
    honest_footer()


if __name__ == "__main__":
    main()
