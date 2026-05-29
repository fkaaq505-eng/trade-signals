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
`sweep.py` (param search) · `compare.py` (strategy bake-off) · `data.py`
(Yahoo fetch) · `watchlist.txt` (= SPY) · `README.md` · `NOTIFY.md` (phone setup).

## Next steps (in order)
1. **Walk-forward validation (priority)** — confirm 82% isn't curve-fit. Train on
   older years, test on held-out recent years; report OUT-OF-SAMPLE win/net/DD.
   Build as `walkforward.py`. Be honest if it doesn't hold up.
2. **Scale-in test** — Connors-style: add at deeper oversold (e.g. RSI2<5 while
   already long); needs partial-position support in `engine.py`. Adopt only if it
   beats current on win AND net AND drawdown (`compare.py` discipline).
3. Optional: VIX-regime filter, weekly performance push, short side.
4. Re-tune yearly; update `news.FOMC_DAYS` with next year's Fed calendar.

---

### Opening prompt for the new account
> Continue my trading-signals project. Clone https://github.com/fkaaq505-eng/trade-signals
> (gh authed as fkaaq505-eng), read HANDOFF.md, and confirm the SPY meanrev signal +
> the phone notifier still work. I'm in Saudi time (AST). Keep it free, paper-only,
> and stay brutally honest about performance — no fake win-rate tricks. ntfy topic is
> nema-sig-401eccea14. Don't touch the Obsidian vault or other Nema files.
