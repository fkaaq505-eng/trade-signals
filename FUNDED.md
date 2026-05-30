# Funded / Prop-Account Research + Strategy (honest findings)

Deep-research summary for trading funded prop-firm accounts (FTMO, Topstep, Apex,
MyFundedFutures, etc.), and what this repo now provides for it.

## The brutal truth (sourced)

- **Pass rate is 5–10%. ~94% fail.** Even passing rarely pays: only ~7% of funded
  accounts ever see a payout; 40–50% blow up within 90 days.
- **~80% fail on RISK MANAGEMENT, not strategy.** The killer is the drawdown limit:
  a $100k account often has only a ~$2–5k loss window, so normal swings are fatal
  when oversized.
- **What passers actually do:** risk **0.5–1% per trade**, ~**3 trades/day**, use
  **60–80% of the time window** (don't rush the target), and **always use a stop**.
  Failers risk 2–3%, take ~7 trades/day, and rush.

Sources: apextraderfunding.com, funderpro.com, pickmytrade.trade, tradezella.com,
the5ers.com, quantvps.com.

## The standard strategy: Opening Range Breakout (ORB)

Why it's the default prop setup: intraday, **flat by close** (no overnight gap),
**defined stop** (opposite side of the opening range), clear R:R, ~one trade/day —
fits every firm's rules. Rules implemented in `orb.py`:

- Opening range = first 30 min of the session (high/low).
- Enter on a break of the range (stop-order). Stop = the other side of the range.
- Target = 1.5× the range. Flat by the close otherwise.
- Trend filter: only take breakouts in the prior day's direction.
- Risk a fixed 1% of the account per trade; size position from the stop distance.

## But — honest edge verdict

ORB's edge is **weak and eroding**: ~67% of breakouts are false (double-breaks),
it's heavily curve-fit-prone, and "doesn't work very well anymore" on indices.
Our own run on SPY 15m (~60 days, all free data allows) gave **negative
expectancy (−0.018R/trade, 41% win)** — no edge. Sources: quantifiedstrategies.com,
edgeful.com, buildalpha.com.

**Conclusion:** there is no proven money-making entry signal here. The thing that
passes funded challenges is the **risk discipline**, not the breakout. So `orb.py`
is best used as a **disciplined daily PLAN + risk-sizer**, not a predicted winner.

## Why we can't just "validate it"

Free Yahoo data caps intraday history (~60 days at 15m). 60 days = one regime =
overfit noise, not proof. To honestly validate ANY intraday funded strategy you
need multi-year fine bars: export a CSV from TradingView ("Export chart data"), or
download free from Alpaca / Polygon, then `python orb.py your_file.csv`. Forward
paper-test before risking a real evaluation.

## Files

`orb.py` (ORB daily plan + illustrative backtest) · `funded_intraday.py` (RSI2
intraday, hard stop + EOD-flat) · `fundeval.py` (eval pass/fail simulator) ·
`funded.py` (MAE / drawdown reality check) · `data_csv.py` (load real intraday CSV).
