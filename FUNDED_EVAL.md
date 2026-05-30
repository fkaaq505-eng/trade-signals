# Highest-Probability Funded-Eval Playbook

**Goal:** maximise the probability of PASSING a funded futures evaluation, honestly.
**Premise (proven, HANDOFF 7-19):** there is no validated trading edge on accessible
free data — ORB/RSI2/VWAP/FVG/sweep all lose out-of-sample after fees on SPY/QQQ, real
NQ/ES futures, NQ/ES index CFDs (5.4y), and BTC/ETH. So passing is NOT about a magic
signal. It is a **finite probability game** you optimise with firm choice, sizing, and
attempts. Tool: `eval_montecarlo.py` (Monte Carlo, validated against gambler's ruin).

## The core math (do not forget this)
P(pass) is **capped by the barrier ratio = drawdown_buffer / (buffer + profit_target)**
(gambler's ruin). With no edge, **no sizing trick beats the ceiling.** You raise your
odds only by: (1) picking a firm with a higher barrier ratio + forgiving rules, (2)
sizing well enough to *reach* the ceiling (never trade timid), (3) taking multiple
cheap-reset attempts: `P(>=1 pass in k) = 1-(1-p)^k`.

## Firm comparison (50k plans, researched May 2026 — VERIFY before paying)
| Firm / plan | DD type | buffer | target | barrier | consistency | min/max days | eval $ | reset $ |
|---|---|---|---|---|---|---|---|---|
| **Bulenox Opt.1** | intraday-trail (BIG buffer) | $2,500 | $3,000 | **0.45** | none | 0 / none | $87 | $78 |
| **Alpha Futures Zero** | EOD-lock @ start | $2,000 | $3,000 | 0.40 | none | 1 / none | $119 | $119 |
| **Apex 4.0 EOD** | EOD-lock @ +$100 | $2,000 | $3,000 | 0.40 | none | 1 / 30d | ~$20 promo +$99 act | ~$20 |
| Topstep | intraday-trail | $2,000 | $3,000 | 0.40 | **50% (hard)** | 0 / none | $49 | $49 |
| Elite Trader STATIC | static (never trails) | $2,000 | $4,000 | 0.33 | none | 5 / none | $449 | — |

Avoid for pass-probability: Topstep (intraday + 50% consistency), Earn2Trade (10 min
days, 30% consistency). "Lock" = floor trails by EOD then **freezes permanently** once
you're ~$2,100 ahead — after that the eval is effectively cash-only (no trailing risk).

## Simulator results (E = -0.03R/trade = break-even after fees, disciplined sizing)
Best achievable P(pass) per attempt ≈ the firm's barrier ratio:
| Firm | barrier | sim P(pass)/attempt |
|---|---|---|
| Bulenox Opt.1 | 0.45 | **~44%** |
| Alpha Zero / Apex EOD | 0.40 | **~32%** |
| Topstep | 0.40 (intraday+consistency) | ~31% |
| Elite static | 0.33 | ~29% |

Multi-attempt (Apex EOD, ~$20 promo resets, p≈0.32):
| attempts | P(>=1 pass) | ~eval $ |
|---|---|---|
| 1 | 32% | $20 |
| 3 | **69%** | ~$60 |
| 5 | 85% | ~$100 |
| 8 | 95% | ~$160 |

## The playbook (highest realistic chance)
1. **Firm:** Bulenox Opt.1 for the single highest per-attempt odds (~44%, biggest buffer);
   OR Apex 4.0 EOD for the best *cumulative* odds via cheap promo resets (~$20 each →
   ~85% over 5 attempts for ~$100). Alpha Zero is the cleanest rule set.
2. **Reach the lock/target fast:** size ~2-3% risk/trade (NOT timid — timid grinds you
   out on the negative drift + time limit). On lock-plans, get ~+$2,100 ahead to freeze
   the floor, then coast.
3. **Enforce discipline:** run `risk_engine.py` (auto-size to the DD buffer, daily-loss
   lockout, EOD-flat) so you actually hit the disciplined ceiling, not the 5-20% real rate.
4. **Forward paper-test first:** log every paper trade with `journal.py` until you have a
   stable break-even-or-better record BEFORE risking a real eval fee.
5. **Buy the compounding math:** plan for several cheap-reset attempts, not one hero run.

## The brutal truth (do not let this regress)
- This MAXIMISES P(pass); it does **not** create profit. Every pass is variance; expected
  $ value is negative (eval fees + no edge).
- Documented reality: ~5-20% first-attempt pass rate, only **~7% ever get a payout**
  (FPFX 300k-account study). The sim's ~32-44% is the *disciplined ceiling* you only reach
  by actually enforcing the rules; undisciplined trading collapses to 5-20%.
- **Passing the eval is the easy hurdle.** The funded account is harder — Apex/TPT switch
  to intraday-trailing on the funded (PA) account, plus payout ladders and consistency.
  Most who pass still bleed the funded account out.
- Rules change constantly (Apex 4.0 = March 2026, Alpha Zero = May 2026). Re-verify every
  number on the firm's live rulebook before paying a cent.

Run it: `python eval_montecarlo.py` (or `--trials 50000` for tighter numbers).
