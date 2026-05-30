# Crypto Backtest Findings

**Date:** 2026-05-30  
**Research type:** Out-of-sample backtest. Paper/research only — no orders placed.  
**Fee assumption:** 10 bps per side (0.10% taker fee) = 20 bps round-turn.  
This is a realistic Binance/Coinbase taker rate; many traders pay 4–6 bps as maker.  
Even at maker rates the conclusions below do not change.

---

## Data

| Instrument | Timeframe | Source | Span | Bar count |
|------------|-----------|--------|------|-----------|
| BTCUSDT | 5m | Binance public klines | 2023-01-01 – 2026-05-30 | 358,727 |
| ETHUSDT | 5m | Binance public klines | 2023-01-01 – 2026-05-30 | 358,728 |

OOS split: 70% in-sample (older), 30% held-out (recent). For both instruments the OOS window begins approximately 2025-05-20.

---

## Model Results

### 1. ICT Sweep-Reversal (24h, no RTH filter)
*ict_sweep_crypto.py — midnight UTC opening range, sweep-fade, EOD-flat per UTC day*

| Instrument | Segment | Trades | Win% | Net ExpR | Net TotalR |
|------------|---------|--------|------|----------|------------|
| BTC | IN-SAMP | 838 | 34.5% | -2.70 | -2,266 |
| BTC | OOS | 360 | 42.8% | -2.62 | -944 |
| ETH | IN-SAMP | 838 | 38.1% | -1.89 | -1,585 |
| ETH | OOS | 360 | 41.1% | -1.48 | -535 |

**Verdict: NO EDGE.** Deep negative expectancy in both windows. The midnight-UTC opening range is not a meaningful liquidity construct for crypto; it's an arbitrary clock boundary. The elevated win% vs negative expectancy means wins are small reversals and losses are large breakouts — the classic "picking up pennies in front of a steamroller" pattern.

---

### 2. TJR Crypto — Real Asia/London/NY Sessions (HEADLINE TEST)
*tjr_crypto.py — prior-session H/L as liquidity pools, FVG reversal, EOD-flat per session*

This is the genuinely new test: the actual ICT model on the market it was designed for, with real session structure.

| Instrument | Segment | Setups | Win% | Net ExpR | Net TotalR |
|------------|---------|--------|------|----------|------------|
| BTC | IN-SAMP | 1,991 | 29.5% | -0.57 | -1,127 |
| BTC | OOS | 898 | 26.6% | -0.67 | -602 |
| ETH | IN-SAMP | 2,031 | 32.6% | -0.36 | -732 |
| ETH | OOS | 891 | 28.4% | -0.47 | -419 |

**BTC OOS by session:**

| Session (UTC) | Setups | Win% | Net ExpR | Net TotalR |
|---------------|--------|------|----------|------------|
| Asia (00–08) | 309 | 26.2% | -0.79 | -244 |
| London (08–16) | 318 | 28.3% | -0.55 | -175 |
| NY (13–21) | 271 | 25.1% | -0.68 | -184 |

**Verdict: NO EDGE.** The model loses in every session. London is the least bad (-0.55 R/trade) but still firmly negative. Win rates of 26–33% with -0.5 to -0.8 R average expectancy mean the model is wrong more than it's right, and the losses are proportionally larger than the wins. This is the model on the market it was designed for, with real session H/L levels, tested on 2.4 years of live Binance 5-minute data. It does not work.

The setup count is high (2,000–2,900 total) so statistical noise is not the explanation. The edge simply is not there after 10 bps/side fees.

---

### 3. ORB (UTC-day opening range, 30 min)
*orb_crypto.py — first 30 minutes of each UTC day, trend filter on, RR=1.5*

| Instrument | Segment | Trades | Win% | Gross ExpR | Net ExpR | Net TotalR | MaxDD |
|------------|---------|--------|------|------------|----------|------------|-------|
| BTC | IN-SAMP | 834 | 37.8% | -0.06 | -0.72 | -598 | -598 |
| BTC | OOS | 358 | 41.6% | +0.04 | -0.65 | -231 | -232 |
| ETH | IN-SAMP | 834 | 41.0% | +0.02 | -0.50 | -415 | -416 |
| ETH | OOS | 358 | 41.3% | +0.03 | -0.40 | -143 | -147 |

**Verdict: NO EDGE.** Gross expectancy is marginally positive (BTC OOS: +0.04 R) but the 20 bps round-turn fee easily erases it (net: -0.65 R). Consistent with ORB on SPY/QQQ in this repo. ORB on crypto is the same result: the breakout pattern exists but fees eat the entire margin.

---

### 4. RSI2/VWAP/BB/Trend via engine.py (session=all, crypto)
*engine_crypto.py — 24h session bypass, 8h max hold, 10 bps/side*

**Apparent results (close-of-signal-bar entry):**

| Strategy | Instrument | OOS Trades | Win% | Net ExpR |
|----------|------------|------------|------|----------|
| RSI2 (meanrev) | BTC | 2,953 | 53.2% | +0.097 |
| RSI2 (meanrev) | ETH | 2,768 | 53.3% | +0.054 |
| BB | BTC | 1,103 | 40.8% | +0.095 |
| BB | ETH | 1,124 | 39.9% | -0.008 |
| Trend (EMA) | BTC | 650 | 42.0% | +0.054 |
| Trend (EMA) | ETH | 656 | 40.9% | +0.028 |
| VWAP | BTC | 725 | 32.0% | -0.068 |
| VWAP | ETH | 756 | 35.4% | -0.033 |

**CRITICAL: Close-bar fill artifact — these positive numbers are NOT real edges.**

Investigation reveals a systematic look-ahead bias in the close-of-signal-bar entry assumption. When signals are computed at bar[t]'s close and entry is taken at that same close, a tiny but consistent edge appears. When shifted to the realistic next-bar open fill, the results collapse:

| Strategy | Entry | Win% | Avg PnL/trade |
|----------|-------|------|---------------|
| RSI2 BTC | Close-of-signal bar | 53.2% | +0.014% |
| RSI2 BTC | **Next-bar open (realistic)** | **13.4%** | **-0.190%** |
| BB BTC | Close-of-signal bar | 40.8% | ~+0.01% |
| BB BTC | **Next-bar open (realistic)** | **24.2%** | **-0.194%** |

The apparent edge (1–2 bps/trade) is smaller than a single 5-minute open-to-close gap. In live trading you cannot buy at the exact close of the bar that triggered your signal. The "edge" is completely explained by this fill-price assumption and disappears when corrected.

**Verdict: ARTIFACT. No real edge for any of these strategies on crypto either.**

---

## OOS Buy-Hold Context (OOS window only)

| Instrument | OOS window | Buy-hold return |
|------------|------------|-----------------|
| BTC | 2025-05-20 to 2026-05-30 | -30% to -33% |
| ETH | 2025-05-20 to 2026-05-30 | -20% to -24% |

The OOS window happened to coincide with a significant crypto drawdown period. This makes all active-trading net-negative results even harder to interpret — the strategies were being tested in a down market, which might favor short setups. The ICT/TJR models have no directional bias (they trade both long and short based on sweeps), so this should not materially affect the verdict.

---

## Summary Verdict

| Model | Instrument | OOS Edge After Fees? |
|-------|------------|---------------------|
| ICT Sweep (24h crypto) | BTC | NO — deeply negative (-2.62 R/trade) |
| ICT Sweep (24h crypto) | ETH | NO — deeply negative (-1.48 R/trade) |
| TJR Real Sessions | BTC | NO — negative all 3 sessions |
| TJR Real Sessions | ETH | NO — negative all 3 sessions |
| ORB (UTC midnight) | BTC | NO — fees consume gross edge |
| ORB (UTC midnight) | ETH | NO — fees consume gross edge |
| RSI2/BB/Trend | BTC/ETH | NO — apparent edge is a close-bar fill artifact |
| VWAP | BTC/ETH | NO — negative both in sample and OOS |

**HONEST BOTTOM LINE: Zero validated, positive-expectancy-after-fees, out-of-sample edges found on crypto.**

The ICT/TJR claim that these models "work better on 24h markets" is not supported by any of these results. The FVG-reversal model tested on REAL Asia/London/NY crypto session liquidity levels — the most faithful mechanical implementation possible — loses in every session, on both major instruments, at every reasonable fee assumption.

The same pattern observed across 5+ years of SPY/QQQ testing in this repo repeats on crypto:
- Models show varying degrees of gross signal
- Round-trip costs (10 bps/side for crypto, even 1–2 bps for stocks) erase any marginal edge
- OOS results are consistent with or worse than in-sample (no mysterious OOS improvement)

If an edge is claimed from these signals, the burden of proof requires: (a) a realistic fill model (next-bar open, not close-of-signal-bar), (b) slippage estimate, (c) a second independent OOS window, and (d) forward paper-testing. None of the positive results here survived criterion (a).
