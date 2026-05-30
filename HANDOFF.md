# HANDOFF — trade-signals (for another Claude account / session)

Paste this whole file (or the prompt at the bottom) to the new Claude account to continue.

## What this is
A free, transparent, rules-based **signal tool** for the S&P 500 (SPY). It tells
the user BUY / SELL / HOLD, backtests the strategy, and pushes signals + news to
their phone via a free cloud cron. **It never trades — the user decides and clicks.**

## Repo (source of truth)
- GitHub (private): https://github.com/fkaaq505-eng/trade-signals
- Continue on a new machine:
  ```bash
  gh repo clone fkaaq505-eng/trade-signals && cd trade-signals
  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python cli.py both --strategy meanrev --symbol SPY
  ```

## Current state (all done + verified)
- **Strategy picked:** Connors RSI(2) mean reversion (`--strategy meanrev`), daily.
- **Instrument picked:** SPY only (higher win rate + lower drawdown than QQQ).
- **Tuned config (baked as defaults):** rsi_buy=10, rsi_exit=75, **down_days=2**
  (must fall 2 days before buying the dip), no hard stop, event filter ON. Found
  via `sweep.py` + `compare.py`.
- **Backtest (12y SPY, after fees):** 82.4% win, profit factor 3.41, net +92.2%,
  max drawdown −6.8%, 85 trades. (down_days=2 beat plain RSI2 on every metric.)
- Other strategies tested + rejected: Bollinger reversion (65.8% win), RSI2<5,
  3-down-days. `compare.py` re-runs the bake-off; only adopt a new one if it wins
  on win-rate AND net AND drawdown.
- **News-aware:** Yahoo RSS headlines (keyless) + FOMC(2026)/NFP event flags in
  every push. Optional `FINNHUB_KEY` secret adds CPI etc.
- **Notifier:** `notify.py` → ntfy push. Watchlist via `watchlist.txt` (= SPY).
- **Deployed:** GitHub Actions (`.github/workflows/signal.yml`), 2 pushes/day,
  Saudi-timed (morning brief 08:00 AST + close alert ~23:00/00:00 AST). Verified
  green. ntfy topic `nema-sig-401eccea14` set as repo secret `NTFY_TOPIC`.

## CRITICAL HONESTY (do not let this regress)
- "Super accurate" is not real. 79% win is the honest ceiling and it **still
  trails buy-and-hold on total return** (+77% vs +381% over 12y) — its only edge
  is ~¼ the drawdown. High win rate ≠ more money. Keep the `buy_hold_return_%`
  column visible; never fake win rate with tiny-TP/wide-stop tricks.
- Paper-trade only. The tool must never place orders. User is in Saudi Arabia
  (AST); real brokerages need 18+, so paper is the right path regardless.

## Known loose ends
- **Pushing `.github/workflows/*`.** git's default HTTPS credential here is an OAuth
  App token WITHOUT `workflow` scope, so a plain `git push` that touches a workflow is
  rejected. BUT the `gh` keyring token (fkaaq505-eng) already HAS `workflow` scope — no
  `gh auth refresh` needed. Push workflows with it directly:
  `git -c credential.helper= push "https://x-access-token:$(gh auth token)@github.com/fkaaq505-eng/trade-signals.git" main`.
  Normal (non-workflow) code pushes fine either way. (This is how `orb.yml` got deployed.)
- Optional: free Finnhub key → `gh secret set FINNHUB_KEY -b"KEY" --repo fkaaq505-eng/trade-signals`.

## Files
`cli.py` (entry) · `strategy.py` (indicators/signals: trend/meanrev/bb) ·
`engine.py` (backtest+live) · `sessions.py` (intraday session filter) ·
`news.py` (headlines+events) · `notify.py` (ntfy push, short message) ·
`sweep.py` (param search) · `compare.py` (strategy bake-off) ·
`walkforward.py` (out-of-sample validation) · `vixtest.py` (VIX-regime experiment) ·
`funded.py` (prop MAE/drawdown reality check) · `fundeval.py` (eval pass/fail sim) ·
`funded_intraday.py` (intraday hard-stop + EOD-flat) · `orb.py` (Opening Range
Breakout + daily plan) · `intraday_compare.py` (accuracy-vs-profit bake-off) ·
`intraday_oos.py` (intraday OOS test, incl EMA-trend) · `orb_oos.py` (ORB OOS on real
5m, RTH-filtered, fee-in-R) · `ict_sweep.py` (ICT/TJR sweep-reversal OOS test, no edge) ·
`journal.py` (log YOUR paper trades → real win/expectancy/net-after-fees, any strat) ·
`autojournal.py` (system auto-logs ORB TP/SL/EOD outcomes → `journal_orb.csv`) ·
`tjr_bot.py` (TJR "Path to Profitability" model mechanized + OOS-tested, no edge) ·
`screen.py` (screen ETFs for the meanrev edge → the frequency basket) ·
`data_csv.py` (load OHLCV CSV) ·
`alpaca_fetch.py` (pull real bars via Alpaca CLI, read-only) · `FUNDED.md` (research) ·
`data.py` (Yahoo fetch) · `watchlist.txt` (= SPY) · `README.md` · `NOTIFY.md` (phone setup) ·
`.github/workflows/signal.yml` (meanrev cron, the validated edge) ·
`.github/workflows/orb.yml` (ORB paper-plan cron, 10:00 ET, no edge) ·
`.github/workflows/autojournal.yml` (post-close cron, auto-logs ORB outcome, commits record).

## Next steps (in order)
1. **Walk-forward validation — DONE (`walkforward.py`).** Verdict: **not overfit.**
   True out-of-sample (re-tuned each year on PRIOR data only) = **78.4% win**, vs
   82.4% in-sample; ~4pt shrink = normal optimism. Mode A (baked params on
   held-out 2019–2026) = 80.7%. BUT: 2 of 8 OOS years lost money (2019, 2022),
   and OOS net 53–57% still trails buy-hold 237% over the same window — the real,
   surviving edge is drawdown (−7/−8% vs holding through 2020/2022). 51–57 OOS
   trades, so ~±11% CI. Run: `.venv/bin/python walkforward.py`.
2. **Scale-in test — DONE, REJECTED.** Connors deeper-oversold add implemented as
   no-leverage fractional tranches in `engine.py` (`--scale-in`, default OFF).
   Bake-off (`compare.py`): scale-in 50/50 (<5) = 83.5% win / 52.3% net / −6.1% DD;
   current all-in = 82.4% / 92.2% / −6.8%. Beats on win + DD + PF but **net craters
   92%→52%** (idle dry powder). Fails the win-AND-net-AND-DD gate → not adopted.
   Mechanism kept as opt-in for future (e.g. if cash earns yield).
3. **VIX-regime filter — DONE, REJECTED as default (`vixtest.py`).** No VIX band
   beats current on win AND net AND DD — the 200SMA already blocks crash-buying.
   Engine supports it opt-in (`vix`/`vix_min`/`vix_max`, default off). NOTE one
   honest lever: `VIX<25` keeps the same 82.4% win and nearly HALVES max drawdown
   (−6.8%→−3.9%), only giving up net (92→69%). Not the default (fails the net
   gate) but a valid choice if you prioritise smoothness; not yet wired to live.
4. **Reliability — DONE.** `notify.py` now pushes a loud "⚠️ trade-signals FAILED"
   alert on any job exception (else a broken cron is silent and looks like HOLD).
   The daily `--brief` morning push already doubles as a liveness heartbeat.
5. Optional/declined: short side (advised against — meanrev sits in cash below
   200SMA, which is WHY drawdown is low; shorting kills that edge). Weekly perf
   push = cosmetic (no positions tracked).
6. Re-tune yearly; `news.FOMC_DAYS` confirmed current for all of 2026.
7. **Funded/prop accounts — REALITY CHECK done (`funded.py`).** Added per-trade MAE
   (max adverse excursion) to the engine/`Trade`. Honest finding: worst trade went
   −11.4% underwater intraday (the close-to-close −6.8% DD hid this); holds up to 12
   days. NOT prop-safe as-is — fails intraday/EOD-flat futures firms outright, and
   one bad trade breaches a 4–5% trailing/daily limit at full size (survivable only
   ~17% sized). Edge = no stop + sit in cash = opposite of prop rules. Best fit
   stays a personal cash/paper account. A real funded variant would be a SEPARATE
   intraday + hard-stop + EOD-flat strategy, scoped to one firm's exact limits.
8. **Funded intraday — STRUCTURE built, EDGE unproven (`funded_intraday.py`,
   `fundeval.py`).** Added `eod_flat` to the engine (close on each day's last bar)
   and an MAE-based eval simulator. RSI2 on 1h SPY + hard ATR stop + EOD-flat gives
   the prop-compatible risk shape (worst MAE −1.95%, no overnight gap) — but on the
   only free data available (~3y, one bull regime) it makes +6–8% while buy-hold
   made +70%: no demonstrated edge. Honest blocker: a money-making intraday edge
   CANNOT be validated on free Yahoo data (intraday history capped). Real funded
   work needs paid multi-year intraday data + forward paper testing. The validated
   DAILY strategy is deliberately KEPT (not deleted) as the only proven asset.
   `data_csv.py` lets `funded_intraday.py <file.csv>` run on real deep intraday data
   (TradingView "Export chart data" CSV, or a free Alpaca/Polygon download) — Yahoo
   has no usable intraday history, and TradingView has no official data API (only
   ToS-violating scrapers that are also bar-limited). Manual CSV export is the clean
   path. Next real step: pull multi-year 5m/1m bars, re-run, then forward-test.
9. **Funded strategy researched + built — `orb.py`, `FUNDED.md`.** Opening Range
   Breakout (the standard prop setup) with evidence-based risk rules (1% risk, stop
   = range opposite, 1.5R target, EOD-flat, trend filter). Research (FUNDED.md):
   pass rate 5–10%, ~80% fail on risk-management not strategy. HONEST EDGE VERDICT:
   ORB is negative-expectancy on SPY 15m free data (−0.018R) — no proven edge.
   `notify.py` has a funded mode: `STRATEGY=orb` pushes a daily ORB PLAN + risk
   guardrails (framed as a plan, NOT a prediction). To make it the LIVE push you
   must edit `.github/workflows/signal.yml` (set `STRATEGY: orb` + add a cron ~30min
   after the US open, e.g. `0 14 * * 1-5` for 10:00 ET EDT) — that needs the
   `workflow` OAuth scope (`gh auth refresh -h github.com -s workflow`). The default
   stays `meanrev` (the only validated strategy); ORB is opt-in until validated on
   real intraday data. Recommendation: don't make a no-edge strategy your sole push.
10. **"More accurate" chase — DEAD END, proven (`intraday_compare.py`, VWAP added
    to `strategy.py`).** Built VWAP reversion + an accuracy-vs-profit bake-off of
    high-win-rate intraday families. Result on SPY 15m: most ACCURATE (RSI2 57%
    win) makes +1.3% net; the tighter-stop version is LESS accurate (45%) but more
    profitable (+2.1%); VWAP is 56% "accurate" and LOSES (−0.2%). All trail buy-hold
    (+10.8%). Lesson (the project's core rule, now demonstrated): win rate ≠ money;
    none is a proven edge on free data. Stop chasing accuracy — chase validated
    positive expectancy (needs real multi-year intraday data) or keep `meanrev`.
11. **Intraday OUT-OF-SAMPLE test — DEFINITIVE NO EDGE (`intraday_oos.py`).** Ran on
    the deepest keyless intraday data (1h SPY, ~2y), train older 70% / test recent
    30%. Every strategy that was profitable in-sample (RSI2 +10%, Bollinger +3%)
    went NEGATIVE out-of-sample (−3.1%, −0.8%, etc.) while OOS buy-hold made +20.7%.
    The in-sample edges were overfit and died on unseen data. Conclusion: there is
    NO validated funded/intraday edge obtainable on free data — not ORB, RSI2, VWAP,
    or Bollinger. A real search needs years of 5m/1m bars via CSV (Alpaca/Polygon),
    and the strong prior is it still won't beat buy-hold. The honest funded takeaway
    is the research one: success is risk discipline, not a strategy we can hand over.
12. **REAL 5-min data tested — FINAL: NO EDGE (`alpaca_fetch.py`).** Installed the
    Alpaca CLI (`brew install alpacahq/tap/cli`, auth via `alpaca profile login`,
    paper/OAuth, READ-ONLY data use only), pulled **114,388 real SPY 5-minute bars
    (2021–2026, ~5.4y)** and ran `intraday_oos.py spy_5m.csv`. Result: ALL four
    strategies LOSE in-sample AND out-of-sample (RSI2 −25%/−14%, VWAP −7%/−2%, etc.)
    while OOS buy-hold made +32%. Root cause: gross per-trade edge ≈0.01% < ≈0.02%
    round-turn cost → **intraday SPY mean reversion is a structural loser after fees.**
    Conclusion is now settled on real, deep, out-of-sample data: there is no funded
    intraday edge here. Re-pull data: `python alpaca_fetch.py SPY 5Min 2021-01-01
    spy_5m.csv` (CSVs are gitignored). NEVER run alpaca trading/position/--live cmds.
13. **Momentum family tested OOS + ORB DEPLOYED as a PAPER push (`orb_oos.py`,
    `orb.py`, `.github/workflows/orb.yml`).** Closed the one gap: items 7-12 were all
    MEAN REVERSION; the momentum/breakout side (what funded survivors actually use) had
    never hit the deep 5m data. Now it has — same verdict, NO live edge:
    - `orb_oos.py` (RTH-filtered so the opening range = the real 9:30 ET open; fee-in-R;
      70/30 OOS) on the 5.4y 5m data: ORB net OOS expectancy = **−0.074R/trade** after
      fees (looked +0.029R in-sample = overfit). Added EMA-trend to `intraday_oos.py`:
      also loses OOS (−2.7%). Both momentum AND mean-reversion now confirmed no-edge.
    - Swept 24 ORB configs (RR × OR-window × trend-filter), tuned on TRAIN → checked
      OOS. Train-best still loses OOS. A **trend-OFF + high-RR (3:1)** cluster showed
      positive OOS — but year-by-year it **DECAYED**: +2021-24, flat 2025, −2026 (−11R
      the last 12 months). Classic dead/dying edge. A "backtest till Jan 2026" cutoff
      shows +103.6R and HIDES that funeral — never gate on a flattering end date; gate
      on the most-recent OOS window. Did NOT promote it.
    - **Deployed anyway as an honest PAPER forward-test** (not as an edge): new
      `orb.yml` cron fires 10:00 ET (dual-DST crons + `near_us_open()` gate, laptop-
      closed, `STRATEGY=orb`). The push (`notify.py:push_orb_plan`) is plain-language,
      shows S&P 500 index "thousands" levels (SPY in brackets) + AST times + a one-order
      bracket framing, labeled "no proven edge · paper". `meanrev` (signal.yml) is
      untouched — still the only validated edge and still main.
    - `orb.py` refactored: `backtest_orb_records`/`OrbTrade` expose per-trade detail;
      `backtest_orb` keeps its (R-list, plan) shape so `notify.py` is unaffected.
    - Industry research (WebSearch; perplexity key was 401): funded pass rate 5-10%,
      ~80% fail on RISK MGMT not strategy, survivors risk 0.5-1%/trade. **As of
      2026-03-01 Apex 4.0 + Topstep BAN overnight** → EOD-flat now mandatory; Topstep
      EOD-trailing DD is easier to survive than Apex intraday-trailing. No public
      intraday edge survives fees — matches our data. Funded success = risk discipline,
      not a strategy. Only real perf lever left = the VIX<25 meanrev option (item 3):
      same 82% win, ~half drawdown, less net — NOT enabled (user's call: return↔smooth).
14. **Trade journal — DONE (`journal.py`).** Record-only logger for the user's actual
    paper trades → real win% / expectancy% / net-after-fees / profit factor / max-DD,
    filterable by strategy tag. The honest way to measure ANY method, incl. a
    discretionary TJR/ICT "feel" (full ICT is unfalsifiable, so only a real logged
    sample can judge it). Fees on both legs, recomputed from raw fields (no drift).
    Local CSV (`journal.csv`, gitignored = private). Usage: `python journal.py add
    --strat meanrev --symbol SPY --side long --entry 756.5 --exit 761.2 --size 100`,
    then `python journal.py stats [--strat X]`. Rule printed: expectancy>0 AND PF>~1.3
    over 30+ trades = real edge; high win% + negative expectancy = the win-rate trap.
15. **Auto-journal — DONE (`autojournal.py`, `.github/workflows/autojournal.yml`).**
    The system logs its OWN ORB outcomes: each completed day it replays the ORB plan,
    checks the real bars for TARGET / STOP / EOD-flat, and appends the realized trade
    (1%-risk sizing, fees) to `journal_orb.csv`. Idempotent (dedup by date; today only
    after post-close 21:00 UTC). New `autojournal.yml` cron runs 21:30 UTC (post-close)
    and COMMITS `journal_orb.csv` back via the built-in `GITHUB_TOKEN` (`permissions:
    contents: write`) so the record persists — a hands-off forward paper-test. NOTE:
    `journal_orb.csv` is the only CSV un-gitignored (`!journal_orb.csv`); the manual
    `journal.csv` stays private/local. Backfilled 46 days on first run: 41% win,
    −$1,793, PF 0.87 — confirms ORB has no edge live, exactly as the OOS tests said.
    View: `python journal.py --file journal_orb.csv stats --strat orb`.
16. **TJR "Path to Profitability" — LEARNED + TESTED, NO EDGE (`tjr_bot.py`).** User
    asked to "make the bot learn" the 14-video TJR series. Can't watch video → pulled
    all 14 transcripts (`youtube-transcript-api`; yt-dlp got bot-throttled). Extracted
    the mechanical core: session-liquidity RAID (stop-hunt) → break of structure →
    Fair Value Gap entry → stop past the raid → target opposite liquidity, 1-3% risk.
    Mechanized + OOS 70/30 on real 5m SPY AND QQQ (Nasdaq ≈ TJR's NQ): BOTH NEGATIVE —
    SPY OOS −0.05R, QQQ OOS −0.12R, ~30-37% win. Adapted to stocks (PDH/PDL = the
    liquidity pool, since SPY/QQQ lack 24h Asia/London sessions and Alpaca has no
    futures — an honest proxy, not the exact hours). FIRST cut showed 100% win/+5R =
    a look-ahead bug (returned target R without simulating stop-vs-target path); fixed
    to walk bars forward. Same verdict as ORB/RSI2/VWAP/ict_sweep. The series' real
    value = discipline/psychology ("flow state"), NOT a codeable edge — measure any
    discretionary attempt with `journal.py`. Transcripts pulled to /tmp (not committed).
17. **Frequency basket — RE-ENABLED with edge-validated ETFs (`screen.py`, watchlist).**
    User wanted more-frequent/"daily" action. Held the line: every daily-single-symbol
    and intraday method LOSES (items 7-16) — frequency is the losing zone. Honest answer
    = run the SAME validated meanrev edge across MORE equity index/sector ETFs (the edge
    needs equities' upward drift + index mean reversion; forex/futures/crypto lack it, so
    it does NOT transfer — futures-intraday already proven to lose). Screened 24 liquid
    ETFs (12y daily meanrev, baked config); 8 cleared the gate (win>=72% AND net>0 AND
    >=30 trades): **SPY QQQ IWM MDY VTI XLY XLI XLK**. ETFs (not single stocks) → no
    earnings gaps / can't go to zero. `watchlist.txt` set to these 8; `notify.py` is
    already multi-symbol so the existing cron auto-pushes them — NO workflow scope needed
    (watchlist is a normal file). Frequency ~1-2 signals/week, BURSTY (correlated names
    cluster in dips) — NOT truly daily; nothing profitable is. Rejected DIA/XLF/XLE/XLV/
    XLP/financials/intl (win too low or net weak). Caveat: VTI≈SPY and XLK≈QQQ correlated
    (drop for less overlap); IWM/MDY carry higher drawdown (−13 to −26%) but pass the gate.
18. **THE FUNDED QUEST — directive for the next agent (use everything, stay honest).**
    User wants to PASS a funded/prop account and asked the next account to throw full
    power at it (parallel sub-agents, deep research, paid data if needed). HARD HONESTY
    (do not regress): every funded-LEGAL strategy tested in this repo LOSES out-of-sample
    after fees — ORB, RSI2-intraday, VWAP, Bollinger, EMA-trend, ICT-sweep (`ict_sweep.py`),
    full TJR-FVG model (`tjr_bot.py`) — all on real 5.4y Alpaca 5m SPY+QQQ. DO NOT re-run
    these; they are dead ends. The genuinely UNEXPLORED frontier (where "everything" has
    a real shot):
      (a) REAL FUTURES DATA — only stock proxies (SPY/QQQ) were tested. TJR/ICT trade
          NQ/ES, 24h, real Asia/London sessions. Get NQ/ES 1-5m history (Databento is
          cheap/paid; or other) → test the session-liquidity + FVG model on the ACTUAL
          instrument and hours. Never done here.
      (b) FOREX + CRYPTO — 24h markets ICT/sweep models are NATIVELY designed for; never
          tested here. BTC/ETH 1-5m is FREE + keyless (Binance/Coinbase/Kraken public
          APIs) → write a loader like `alpaca_fetch.py`, OOS-test sweep/FVG/ORB there.
          Crypto has the 24h + volatility + retail-stop liquidity these models target.
      (c) THE DISCIPLINE / RISK ENGINE (most important, most honest) — research is
          unanimous: ~80% fail funded on RISK MGMT, not strategy; survivors risk
          0.5-1%/trade, ~3 trades/day, don't rush. Build a bot that ENFORCES the firm's
          rules: auto position-size capped to the trailing/daily DD limit, daily-loss
          lockout, max-trades/day, mandatory EOD-flat, consistency-rule tracker, profit-
          target pacing. `fundeval.py` already simulates pass/fail — extend it into a live
          guardrail. THIS is the honest "thing that lets you pass": a tested instrument +
          iron risk control, NOT a magic entry signal.
    HOW: spawn parallel sub-agents (one per avenue), deep WebSearch research (perplexity
    key was 401), Alpaca CLI for READ-ONLY data + free crypto APIs. RULES UNCHANGED:
    brutally honest, OOS + fees on EVERYTHING, NO fake win-rate, paper-only, never real
    orders. Forward-test any candidate with `journal.py` / `autojournal.py` before trust.
    Set honest expectations: most funded attempts fail regardless; the edge is discipline;
    a profitable intraday signal may simply not exist on accessible data — if the OOS
    tests say so, SAY SO. Do not sell hope. The validated daily meanrev (15-ETF basket)
    stays the user's PERSONAL-account tool; it is NOT funded-legal (overnight + no stop).
19. **THE FUNDED QUEST EXECUTED — all 3 frontiers tested, SETTLED (3 parallel sub-agents,
    2026-05-30).** Item 18's three "genuinely unexplored" avenues are now done, free ($0 —
    user has no money; Databento declined). Verdict: **no strategy edge anywhere; the only
    real deliverable is the risk engine.** Independently re-verified each agent's numbers.
    - **(A) REAL FUTURES — `futures_fetch.py`, `tjr_futures.py`, `FUTURES_FINDINGS.md`.**
      Got real instruments FREE: Yahoo NQ=F/ES=F 1h (~2.4y), and **Dukascopy index CFDs**
      (`dukascopy-python`, free `freeserv.dukascopy.com`, no account) — E_NQ-100 + E_SandP-500
      **5m, 5.4y, ~370k bars each** + 1h. TJR FVG run on REAL ICT session pools (Asia/London/NY,
      prior-day session H/L — no look-ahead, verified) on the actual instrument + 23h hours.
      Result: every model NEGATIVE OOS after fees EXCEPT Duka-CFD TJR showed OOS +0.115R(ES)/
      +0.049R(NQ) — SCRUTINIZED + REJECTED: t-stat 0.84/0.37 (insignificant, need >2), OOS
      thirds DECAY +0.19→+0.34→−0.19 (ES) / +0.47→+0.01→−0.34 (NQ), last 60 trades −0.36/−0.45R.
      Dead/regime-luck signal, negative in the recent window (= same disease as ORB item 13).
      The instrument-and-hours gap is closed: real NQ/ES + real sessions = same NO EDGE as the
      SPY/QQQ proxy. (Fees: NQ 1.75pt RT, ES 0.50pt RT, CFD 3bps RT.)
    - **(B) CRYPTO — `crypto_fetch.py`, `tjr_crypto.py`, `ict_sweep_crypto.py`, `orb_crypto.py`,
      `engine_crypto.py`, `CRYPTO_FINDINGS.md`.** Binance public klines (keyless), **BTC+ETH 5m,
      2023–2026, ~358k bars each.** TJR FVG on REAL Asia/London/NY UTC session pools (the model's
      native 24h market) + ICT sweep + ORB: ALL negative OOS after 10bps/side taker. The 24h-market
      hypothesis is FALSIFIED — fails on the actual 24h instrument too. One trap caught: engine
      RSI2/BB/trend on crypto showed +OOS R BUT it's a risk-weighting illusion (+0.095R while
      −0.19%/trade) AND a same-bar-close fill artifact (next-bar-open fill, verified, stays negative).
      Fixed `engine_crypto.py` to print net_exp% beside net_expR so the "R-positive/money-negative"
      illusion is visible in the tool, not just the doc.
    - **(C) RISK / DISCIPLINE ENGINE — `risk_engine.py`, `test_risk_engine.py`, `fundeval_live.py`.
      THE deliverable.** Immutable state machine that ENFORCES prop rules (paper-only, never orders):
      auto position-size capped to MIN(DD-buffer, risk%≈0.5–1%); daily-loss lockout; max-trades/day;
      mandatory EOD-flat; **Apex intraday-trailing vs Topstep EOD-trailing** modes; consistency-rule
      tracker; profit-pace. Presets APEX_50K/100K (2.5% trail), TOPSTEP_50K/100K (4% trail) — defaults,
      verify vs live rulebook. `can_enter/register_fill/register_close/on_new_day/must_flatten` API.
      **61/61 unit tests pass** (stdlib unittest: `python test_risk_engine.py`). `fundeval_live.py
      --compare [--firm topstep]` runs the meanrev stream through the guardrail: disciplined sizing
      survives the worst −11% MAE trade that naive 20% sizing nearly blows — but daily meanrev is
      ~7 trades/yr, far too slow for a 30-day clock, so it's STILL not funded-legal. The engine does
      NOT create an edge; it preserves capital + enforces discipline on whatever instrument has one.
    - **BOTTOM LINE (do not regress):** across every funded-legal strategy × every accessible free
      market/instrument/timeframe (SPY/QQQ 5m, NQ/ES futures 1h, NQ/ES index CFDs 5m 5.4y, BTC/ETH
      5m) — NO validated, statistically-significant, time-stable, post-fee, OOS positive expectancy
      exists. The honest path to passing a funded eval is IRON RISK DISCIPLINE (the engine), applied
      to a tested instrument, accepting that most attempts fail regardless. Not a magic signal — there
      isn't one on free data. Big data CSVs are gitignored; re-pull via `futures_fetch.py`/`crypto_fetch.py`.
20. **PASS-A-FUNDED system built + set as MAIN focus (`eval_montecarlo.py`, `funded_forward.py`,
    `FUNDED_EVAL.md`; extends `risk_engine.py`).** User asked for "the best strat to pass the
    funded, set as main." Since no entry edge exists (items 7-19), reframed honestly as a
    PROBABILITY + DISCIPLINE game and built the tools:
    - `eval_montecarlo.py` — Monte Carlo of the eval as a finite barrier game; validated against
      closed-form gambler's ruin (static-DD breakeven ≈ barrier ratio). CORE TRUTH: **P(pass) is
      capped by the barrier ratio buffer/(buffer+target); no sizing trick beats it without an
      edge.** Levers: firm/DD-type, size (timid is strictly worst; bold → one coin-flip at
      win-rate), attempts (1-(1-p)^k). Levers INTERACT (skew has no universal best) → trust the
      joint optimiser, not single-lever rules. Researched 2026 firm rules (sub-agent): Topstep is
      intraday-trail + 50% consistency (HARD); winners are EOD-"lock" firms (Alpha Zero, Apex 4.0
      EOD — floor freezes once ~+$2,100) and big-buffer Bulenox (ratio 0.45). Disciplined ceiling
      ~32-44%/attempt vs real documented 5-20%; only ~7% ever get a payout.
    - `FUNDED_EVAL.md` — the playbook (firm table, the barrier math, multi-attempt $-cost, caveats).
    - `funded_forward.py` — live PAPER forward-test of one attempt: risk_engine sizes every trade to
      the DD buffer, enforces daily lockout / max-trades / EOD-flat, tracks progress, flags PASS/FAIL,
      logs closed trades to `journal.csv` (strat=funded). State persists in `funded_state.json`
      (gitignored). Commands plan/fill/close/status/reset. Tested end-to-end (PASS, DD-breach FAIL,
      lockout, journal scoring). Global flags (`--firm/--now`) go BEFORE the subcommand (argparse).
    - **"Set as main":** `funded` is now a first-class `cli.py funded` command and the README leads
      with the funded system — the project's primary focus. DELIBERATELY did NOT hijack the phone
      cron to push the no-edge tracker (statefulness + the honesty rule: don't push a no-edge thing
      as the sole signal). The notifier still pushes the VALIDATED meanrev (signal.yml). To add phone
      pushes of eval progress later, commit `funded_state.json` back from a cron like autojournal.yml.
      NOTE: risk_engine's eod-mode failure message hardcodes "Topstep" even for apex_eod (cosmetic;
      numbers correct). Honesty held: maximises P(pass), does NOT make money; EV negative; passing
      the eval ≠ keeping the funded account.
21. **PAYOUT-VERIFIED firm/market/frequency + noty + project refocused (`FUNDED_EVAL.md`,
    `notify.py` funded mode, `.github/workflows/funded.yml`).** User: "set my noty, which market,
    is Bulenox real/pays, how often, sole purpose = pass a VERIFIED funded + get payouts." Did all,
    honestly:
    - **Noty:** `STRATEGY=funded` → `notify.py:push_funded_plan()` pushes a daily discipline plan
      (firm rules, sizing, market, frequency, live progress from funded_state.json if present).
      `funded.yml` cron fires one weekday push ~16:00 AST (pre-US-open), reuses the existing
      NTFY_TOPIC secret. Degrades safely on any error.
    - **Bulenox verdict (sub-agent, sourced):** REAL + pays (Trustpilot 4.8/1.5k, documented
      withdrawals) BUT **RISKY** — an undocumented "flip-day" rule (Master Agreement §5.6) has
      denied rule-compliant payouts. Use only as a secondary. Corrected eval_montecarlo: it still
      shows Bulenox highest pass-ODDS (big buffer, 0.45) but now warns pass-odds ≠ get-paid.
    - **Firm for PASS×PAYOUT:** #1 **Topstep** (EOD-trail BOTH eval+funded, cleanest payouts, no
      lifetime cap, Standard path = NO consistency — FIXED my earlier mis-model that had Topstep as
      intraday+consistency; it is EOD). #2 **Apex 4.0 EOD** (cheapest ~$20 promo resets, automated
      Deel payouts no human can deny, $598M+ paid, but 6-payout ~$13k lifetime cap). #3 Take Profit
      (funded PRO = intraday trap). Tooling default stays apex_eod (cheapest for a no-money user).
    - **Market:** micros — **MES** (default, smoother, easier consistency) or MNQ (momentum). Tick
      values MES $1.25 / MNQ $0.50. US-open session (16:30-18:30 AST), flat by close.
    - **Frequency:** 2-5 trades/day over ~10-15 trading days (~2-3 weeks) — consistency rules force
      spreading gains; rushing one big day voids payouts.
    - **The honest CHAIN (in FUNDED_EVAL.md):** P(pass ~30-44%) × P(reach funded payout ~30-40%) ×
      firm pays = ~8-15% optimal, ~5-6% realistic (Topstep's own data: 16.8% reach funded, 33% of
      those ever paid). EV negative; not regulated; firms profit on fees. Refocused README + this
      doc on the funded goal but KEPT meanrev (only validated edge) as the phone push.

---

### Opening prompt for the new account
> Continue my trading-signals project. Clone https://github.com/fkaaq505-eng/trade-signals
> (gh authed as fkaaq505-eng), `python3 -m venv .venv && .venv/bin/python -m pip install
> -r requirements.txt`, then read HANDOFF.md FULLY before doing anything. Confirm the
> SPY meanrev signal still runs: `.venv/bin/python cli.py both --strategy meanrev`.
>
> STATE (May 2026): The DAILY SPY meanrev strategy is the only validated edge (82% win,
> walk-forward-confirmed 78% out-of-sample) — keep it; it's what the phone notifier
> pushes. The FUNDED/prop-account investigation is COMPLETE and the answer is NO EDGE:
> ORB, intraday RSI2, VWAP, Bollinger AND the momentum family (ORB high-RR, EMA-trend)
> were all tested out-of-sample on real Alpaca 5-minute data (~5.4y) and ALL lose (gross
> edge < fees); ORB's best config even DECAYED to negative in the last 12 months. ORB is
> now deployed ONLY as a clearly-labeled PAPER forward-test (orb.yml, 10:00 ET cron) —
> not an edge. Don't redo this or chase "more accurate" — it's the win-rate trap; see
> HANDOFF items 7–13.
>
> Rules: free + paper-only, NEVER place real orders (the Alpaca CLI is installed but is
> for READ-ONLY data pulls only — never trading/position/--live). Be brutally honest, no
> fake win-rate tricks. I'm in Saudi time (AST). ntfy topic nema-sig-401eccea14. Don't
> touch the Obsidian vault or other Nema files. Data CSVs are gitignored; re-pull with
> `python alpaca_fetch.py SPY 5Min 2021-01-01 spy_5m.csv` (needs `alpaca profile login`).
