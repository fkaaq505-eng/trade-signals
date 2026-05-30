# Funded Eval → Payout Playbook (verified May 2026)

**Project's sole purpose now:** pass a funded futures evaluation and extract a real
payout. This doc is the verified plan. Read the caveats — they are the truth.

## The premise you cannot escape
There is NO validated trading edge on any data you can access (proven across SPY/QQQ,
real NQ/ES futures, NQ/ES index CFDs 5.4y, BTC/ETH — HANDOFF 7-19). So this is a
**probability + discipline** game, not a strategy. Two consequences:
1. You can MAXIMISE the chance to pass and to extract a payout. You cannot make it
   positive-EV. Most attempts lose the eval fee. You said you have no money — treat every
   eval fee as money you can afford to lose, because you probably will.
2. "Getting paid" is a **chain**, and each link is a fresh gamble with no edge:

```
   P(pass eval)      ~30-44% per attempt (disciplined ceiling; real traders 5-20%)
 × P(reach 1st payout on the FUNDED acct before breaching)   ~30-40%
 × firm actually pays (policy + integrity)                   ~ok at Topstep/Apex
 = P(eval fee -> a real payout)  ~ 8-15% optimal, ~5-6% realistically.
```
Topstep's own 2025 data: ~16.8% pass to funded, ~33% of funded ever get a payout →
**~5-6% of all starters ever see a dollar.** That is the honest number.

## Which FIRM — ranked for PASS *and* getting PAID (not just pass-odds)
Pass-odds alone says Bulenox (biggest buffer). But pass-odds ≠ get-paid. Verified:

| Rank | Firm (50k) | Why | Watch out |
|---|---|---|---|
| **#1 Topstep** | EOD-trailing on BOTH eval *and* funded (no post-pass ambush); cleanest payouts; **no lifetime cap**; longest track record (pre-2015); Standard path = **no consistency rule** | $49/mo; 90/10 split; $30/payout; first payout capped ~$2k |
| **#2 Apex 4.0 EOD** | **Cheapest to attempt** (~$20 promo evals → best for no money); **automated payouts via Deel (no human can deny)**; $598M+ paid; EOD funded DD | 6-payout lifetime cap (~$13k) then account closes; +$99 activation |
| #3 Take Profit Trader | No consistency rule on funded | **Funded PRO = intraday-trailing (harder than eval)** — common post-pass blowup |
| ⚠️ Bulenox | Highest raw pass-odds (big $2,500 buffer) | **Undocumented "flip-day" rule has denied rule-compliant payouts.** Secondary/test only |
| Elite static | True static floor (never trails) | $4k target (ratio 0.33) + $449 → worse overall |

**Your pick:** no money → **Apex 4.0 EOD** (cheap promo resets, automated payouts that
can't be denied by a human, EOD funded). Want max payout integrity and can spend a bit →
**Topstep**. Both are EOD on the funded account — that matters more than the eval.
Bulenox: only as a cheap extra shot, knowing the flip-day risk.

## Payout policy (verified — the part that turns variance into cash)
| Firm | Min days (funded) | First withdrawal | Split | Funded DD | Consistency (funded) | Speed |
|---|---|---|---|---|---|---|
| Topstep | 5 winning days ($150+ each) | ~$2k cap 1st | 90/10 | EOD (no intraday trail) | Standard: none | next day (Wise) |
| Apex EOD | 5 qualifying days ($250+ each) | $500 min; bal ≥ ~$52,100 | 100%→$25k then 90/10 | EOD | 50% best-day at payout | ~5 biz days (Deel) |
| Take Profit | day 1 (after buffer) | bal ≥ ~$52k | 80/20 PRO | **intraday** | none | "fast" (unverified) |
| Bulenox | 5 (funded)/10 (master) | $1,000 min | 100%→$10k then 90/10 | trailing | 40% + flip-day | weekly |

**Extract fast:** with no edge, the optimal funded play is hit the minimum-withdrawal
threshold ASAP and WITHDRAW — don't "build the account," variance will take it back.

## Which MARKET to trade
Futures (these are futures firms). Trade **micros** — they let you size to the small
0.5-1% risk precisely. Tick values (CME): ES $12.50 · **MES $1.25** · NQ $5.00 · **MNQ $0.50**.

- **MES (Micro S&P)** — DEFAULT. Smoother (40-80 pt RTH range), easier to stay inside
  consistency + drawdown. Best for disciplined, rule-based trading.
- **MNQ (Micro Nasdaq)** — finer ticks ($0.50) but ~2-4× the volatility (200-400 pt range).
  Use only if your style is momentum/breakout and you widen stops accordingly.
- Both: ~1-tick spreads, 4M+ contracts/day — plenty liquid.
- **Session:** US RTH, especially the first 90-120 min (9:30-11:30 ET = **16:30-18:30 AST**).
  Peak volume, tightest spreads. Flat by close — no overnight gap risk to your DD.

## How OFTEN you'll trade
- **2-5 trades/day**, only clean setups in the open window. No setup = no trade.
- **~10-15 trading days** to reach the $3,000 (6%) target — NOT 5-6. The consistency rule
  caps any single day's share of profit, so you must SPREAD gains across days. Rushing it
  with one big day can breach consistency and void the payout. (10-15 days = community
  consensus, unverified — no firm publishes it.)
- So one attempt ≈ **2-3 weeks** of disciplined daily trading.

## The playbook
1. **Firm:** Apex 4.0 EOD (budget) or Topstep (integrity). Verify rules on the live
   dashboard the day you buy — they change (Apex 4.0 is weeks old; Topstep changed splits
   Jan 2026).
2. **Market:** MES, US-open session, flat by close.
3. **Size:** risk 0.5-1%/trade via `risk_engine.py` (auto-caps to the DD buffer). Reach
   the lock/target in small steps; never oversize to chase.
4. **Spread it:** 2-5 trades/day over ~2 weeks; keep any single day < ~40% of total profit.
5. **Forward-test first:** run `funded_forward.py` on paper, log with `journal.py`, until
   you have a stable record. If you can't pass on PAPER, do not pay for a live eval.
6. **Attempts:** budget several cheap resets (Apex ~$20). P(≥1 pass in k) = 1-(1-p)^k.
7. **Withdraw fast** once funded and past the threshold. Take the money and run.

## Brutal caveats (do not skip)
- **Not regulated.** No SIPC/FDIC. If the firm closes, you lose. Payouts are a private
  company's promise.
- **Firms profit from eval fees.** <10-20% ever get a payout; ~5-6% of starters at Topstep.
  The business model is failure.
- **Rules change without notice** and can be applied post-hoc (Bulenox flip-day).
- **Passing ≠ keeping it.** The funded account is a second no-edge gauntlet; most who pass
  still end with nothing.
- **This maximises your CHANCE; it does not make money.** Expected value is negative.
  With no money, the honest recommendation is: forward-test on PAPER for free, build the
  discipline, and only ever risk an eval fee you are fully prepared to lose.

Tools: `eval_montecarlo.py` (odds) · `funded_forward.py` (paper forward-test, risk-enforced)
· `risk_engine.py` (sizing/limits, 61 tests) · `journal.py` (real track record).
