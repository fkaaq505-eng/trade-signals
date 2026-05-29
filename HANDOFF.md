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
- **Workflow edits need `workflow` OAuth scope.** The bundled gh token can push
  normal code but NOT `.github/workflows/*`. To change the workflow (e.g. bump
  actions to v6, or change schedule): `gh auth refresh -h github.com -s workflow`
  then push. The symbol pick is done via `watchlist.txt` precisely to avoid
  needing this.
- Optional: free Finnhub key → `gh secret set FINNHUB_KEY -b"KEY" --repo fkaaq505-eng/trade-signals`.

## Files
`cli.py` (entry) · `strategy.py` (indicators/signals: trend/meanrev/bb) ·
`engine.py` (backtest+live) · `sessions.py` (intraday session filter) ·
`news.py` (headlines+events) · `notify.py` (ntfy push, short message) ·
`sweep.py` (param search) · `compare.py` (strategy bake-off) ·
`walkforward.py` (out-of-sample validation) · `vixtest.py` (VIX-regime experiment) ·
`funded.py` (prop MAE/drawdown reality check) · `fundeval.py` (eval pass/fail sim) ·
`funded_intraday.py` (intraday hard-stop + EOD-flat structure) ·
`data_csv.py` (load OHLCV from a CSV — TradingView export / Alpaca / Polygon) ·
`data.py` (Yahoo fetch) · `watchlist.txt` (= SPY) · `README.md` · `NOTIFY.md` (phone setup).

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

---

### Opening prompt for the new account
> Continue my trading-signals project. Clone https://github.com/fkaaq505-eng/trade-signals
> (gh authed as fkaaq505-eng), read HANDOFF.md, and confirm the SPY meanrev signal +
> the phone notifier still work. I'm in Saudi time (AST). Keep it free, paper-only,
> and stay brutally honest about performance — no fake win-rate tricks. ntfy topic is
> nema-sig-401eccea14. Don't touch the Obsidian vault or other Nema files.
