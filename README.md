# trade-signals

A small, transparent, rules-based signal tool for index ETFs/indices
(S&P 500, Nasdaq, anything on Yahoo Finance). It tells you what a fixed
strategy says — **BUY / SELL / HOLD** (with suggested stop/target) — backtests
that strategy on history, and can push the signal to your phone.

> It does **not** connect to a broker, does **not** place orders, and is
> **not** financial advice. It applies math to price data. Every decision
> to act with real money is yours. Paper-trade first.

**Two things live here:**
1. **The validated signal** — daily Connors RSI(2) mean reversion on an index-ETF
   basket (~78% win out-of-sample). The only edge that survived honest testing; it
   is what the phone notifier pushes. Personal account, not funded-legal.
2. **The funded-eval pass system (main focus)** — there is **no** intraday trading
   edge on accessible free data (proven across SPY/QQQ/NQ/ES/CFD/crypto — see
   `HANDOFF.md` 7-19). So passing a funded prop eval is a *probability + discipline*
   game, not a magic signal. `eval_montecarlo.py` computes the highest-odds plan,
   `risk_engine.py` enforces the rules, and `funded_forward.py` runs a live paper
   forward-test. Start here: **[FUNDED_EVAL.md](FUNDED_EVAL.md)**.

## Setup

```bash
cd ~/trade-signals
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Use

```bash
# RECOMMENDED: Connors RSI(2) mean reversion (researched, ~75% win rate)
.venv/bin/python cli.py both --strategy meanrev --symbol SPY
.venv/bin/python cli.py both --strategy meanrev --symbol QQQ
.venv/bin/python cli.py live --strategy meanrev --symbol QQQ

# Alternative: fast intraday EMA crossover (weak edge — see results)
.venv/bin/python cli.py both --strategy trend --symbol SPY --session us_power
```

Symbols: `SPY`/`^GSPC` = S&P 500, `QQQ`/`^NDX`/`^IXIC` = Nasdaq.

## Funded prop evaluation — the highest-chance-to-pass system

No intraday strategy edge exists on free data, so this is engineered as a probability
game: **pick the best-barrier firm, size to reach the ceiling, take cheap-reset attempts,
and enforce iron discipline.** Honest pass odds, not hope.

```bash
# 1. See the highest-P(pass) plan + firm comparison (Monte Carlo)
.venv/bin/python eval_montecarlo.py            # add --trials 50000 for tighter numbers

# 2. Run a live PAPER forward-test of one eval attempt (risk_engine-enforced)
.venv/bin/python cli.py funded --firm apex_eod        # today's disciplined plan
.venv/bin/python funded_forward.py fill --entry 20000 --stop 19960   # open (auto-capped)
.venv/bin/python funded_forward.py close --exit 20030 --side long    # close + journal it
.venv/bin/python funded_forward.py status             # equity / buffer / days / pass-fail
.venv/bin/python journal.py stats --strat funded      # your real track record

# 3. Score it before paying any eval fee. expectancy > 0 over 30+ trades = ready.
```

- **[FUNDED_EVAL.md](FUNDED_EVAL.md)** — the playbook: firm table, the barrier-ratio math,
  the disciplined ceiling (~32–44%/attempt) vs the real ~5–20%, and the brutal caveats.
- `risk_engine.py` — auto-size to the DD buffer, daily-loss lockout, EOD-flat, Apex
  (intraday-trail) vs Topstep (EOD-trail) modes. 61 unit tests.
- **Honest:** this maximises P(pass); it does **not** create profit. Passing the eval is
  the easy hurdle — keeping a funded account with no edge is the hard one. Most fail anyway.

## Two strategies (`--strategy`)

| | `meanrev` (recommended) | `trend` |
|---|---|---|
| idea | Connors RSI(2): buy dips in an uptrend | EMA(20/50) crossover momentum |
| bars | daily | intraday 1h |
| entry | price > 200-day SMA **and** RSI(2) < 10 | EMA cross up + RSI 50–70 + > 200EMA + in session |
| exit | RSI(2) > 65 | EMA cross down / stop / target / time-stop |
| hold | ~2–5 days | hours (capped by `--max-hold-hours`) |
| backtested win rate | **~72–77%** | ~42–50% |
| vs buy-hold | high win rate + ~⅓ the drawdown, but lower total return (mostly in cash) | loses to buy-hold |

Source for meanrev rules: [quantifiedstrategies.com/rsi-2-strategy](https://www.quantifiedstrategies.com/rsi-2-strategy/).

## Tuning (edit `strategy.py` or pass flags)

- meanrev: `--rsi-buy` (entry, default 10), `--rsi-exit` (default 65).
- trend: `--sl-mult` (stop = entry − mult×ATR), `--rr` (reward:risk), `--max-hold-hours`.
- both: `--fee-bps` (cost per side, subtracted from every trade), `--session`.
- `--sl-mult 0` disables the stop (meanrev's default — Connors uses none).
- Long / flat only — no shorting (ask to add it).

## Trading sessions (`trend` only — `--session`, all times ET)

| name | window | use for |
|------|--------|---------|
| `us_power` | 9:30–11:00 | opening drive — most volume + cleanest momentum |
| `us_morning` | 9:30–12:00 | **default** — strong trend, before lunch chop |
| `us` | 9:30–16:00 | full cash session |
| `london_ny` | 8:00–11:00 | EU/US overlap — best for futures (ES/NQ) |
| `all` | 24h | no filter (includes thin, gappy overnight) |

All knobs live at the top of `strategy.py`. Change them, re-run the backtest,
see what happens. That *is* the learning loop.

## Reading the backtest

- `win_rate_%` — how often trades made money. **High win rate alone is a trap**
  (tiny TP + wide stop fakes it). Read it next to net return.
- `profit_factor` — gross win ÷ gross loss. >1 = profitable in the test.
- `avg_trade_%` — average profit per trade, after fees.
- `net_return_%(after fees)` — total compounded return of the strategy.
- `max_drawdown_%` — worst peak-to-trough drop. How much pain to sit through.
- `buy_hold_return_%` — **the honesty check.** If the strategy can't beat just
  buying and holding, the only reason to run it is lower drawdown.

## News & event-risk awareness (auto, free)

Research: mean-reversion breaks around high-impact macro events (FOMC, CPI, NFP) —
they trend, they don't revert. So the tool is event-aware.

- **Headlines** — `news.py` pulls fresh SPY/QQQ headlines from Yahoo RSS (keyless).
  Included automatically in every phone push. Add to a live check with `--news`.
- **Event flag** — built-in 2026 FOMC dates ([Fed](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm))
  + NFP (first Friday). On those days the push warns "HIGH-IMPACT TODAY — expect whipsaw".
- **Backtest filter** — `--skip-events` skips entries on high-impact days. On SPY
  meanrev it nudged win rate 77.2→78%, profit factor 2.44→2.56, drawdown −11.4→−9.5%.
- **Optional richer calendar** — set a free [Finnhub](https://finnhub.io) key as
  `FINNHUB_KEY` to auto-detect more events (CPI etc.). Degrades silently without it.

Sources: [event filters for mean reversion](https://www.buildalpha.com/news-event-trading/),
[free calendar APIs](https://finnhub.io/docs/api/economic-calendar).

## Notifications when you're away

Get a phone push near the US close when a signal fires — laptop closed, no
problem. Runs free on GitHub Actions + ntfy.sh. See **[NOTIFY.md](NOTIFY.md)**.
It notifies only; it never trades.

## Hard truths

1. A good backtest does not mean future profit. Curve-fitting is easy.
2. `--fee-bps` models commission/spread, but **slippage and taxes are not** —
   real results are worse, especially intraday.
3. High win rate ≠ more money. `meanrev` wins ~75% yet still trails buy-hold on
   total return (it sits in cash ~95% of the time); its edge is lower drawdown.
4. Most retail mechanical traders lose money. Assume you might too.
5. Paper-trade any change for months before risking a cent.
