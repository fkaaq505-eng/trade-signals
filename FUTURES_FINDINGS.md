# Futures Research Findings

**Date:** 2026-05-30  
**Scope:** NQ/ES futures and index CFD — the instruments TJR/ICT actually trade,
tested on real overnight-session data for the first time in this repo.  
**Honesty rule:** OOS only. After fees only. No exceptions.

---

## Data Pulled

| Source | Instrument | TF | Span | Bars | Notes |
|--------|------------|-----|------|------|-------|
| Yahoo Finance | NQ=F (E-mini Nasdaq) | 1h | 2024-01-05 → 2026-05-29 (875d / 2.4y) | 13,711 | Real futures, includes Globex overnight |
| Yahoo Finance | ES=F (E-mini S&P 500) | 1h | 2024-01-05 → 2026-05-29 (875d / 2.4y) | 13,713 | Real futures, includes Globex overnight |
| Yahoo Finance | NQ=F | 5m | 2026-03-19 → 2026-05-29 (71d) | 13,552 | Sanity check only — 2 months, too short |
| Yahoo Finance | ES=F | 5m | 2026-03-19 → 2026-05-29 (71d) | 13,551 | Sanity check only — 2 months, too short |
| Dukascopy (free chart API) | E_NQ-100 (Nasdaq CFD) | 5m | 2021-01-03 → 2026-05-29 (1971d / 5.4y) | 370,160 | Index CFD ≈ NQ; mid-price, no roll |
| Dukascopy (free chart API) | E_SandP-500 (S&P CFD) | 5m | 2021-01-03 → 2026-05-29 (1971d / 5.4y) | 370,363 | Index CFD ≈ ES; mid-price, no roll |
| Dukascopy (free chart API) | E_NQ-100 | 1h | 2021-01-03 → 2026-05-29 (1971d / 5.4y) | 31,895 | (built for model dev; tests use 5m) |
| Dukascopy (free chart API) | E_SandP-500 | 1h | 2021-01-03 → 2026-05-29 (1971d / 5.4y) | 31,899 | (built for model dev; tests use 5m) |

**Dukascopy access method:** `dukascopy-python` PyPI package (v4.0.1, free, MIT), 
hits `freeserv.dukascopy.com/2.0/` JSON endpoint. Fetched in 90-day batches (30k row
limit per request) and concatenated. No account or payment required.

**Honest caveat on Dukascopy data:** E_NQ-100 and E_SandP-500 are *index CFDs* quoted 
by Dukascopy Bank at mid-price. They closely track the underlying index (and thus the 
futures) but are NOT the actual futures contract. No roll cost, no basis, slightly 
different hours at session boundaries. All results label them as CFD data.

---

## Fee Assumptions

| Instrument | Round-turn cost | Basis |
|------------|----------------|-------|
| NQ futures (Yahoo) | 1.75 index pts RT | $4.50 commission ÷ $5/tick ×0.25 + 0.25 tick slippage |
| ES futures (Yahoo) | 0.50 index pts RT | $4.50 commission ÷ $12.50/tick ×0.25 + 0.25 tick slippage |
| NQ/ES CFD (Dukascopy) | 1.5 bps per side (3 bps RT) | Spread proxy; no exact exchange commission |
| ICT sweep (stocks bps model) | 1.0 bps per side (2 bps RT) | Same as repo default |

---

## OOS Results Table

All splits: 70% train (older) / 30% test (most-recent). Fees applied on both sides.

### A. TJR Session-Liquidity + FVG Reversal (`tjr_futures.py`)

Uses REAL ICT session H/L pools (Asia 00-07 UTC, London 07-16 UTC, NY 13-20 UTC) as 
liquidity levels — NOT prior-day H/L stock proxy. First raid→FVG setup per day only.

| Dataset | Span | IS n | IS win% | IS expR | OOS n | OOS win% | OOS expR | OOS totalR | Verdict |
|---------|------|------|---------|---------|-------|----------|----------|-----------|---------|
| Yahoo NQ=F 1h | 2.4y | 202 | 30.7% | -0.069 | 87 | 28.7% | **-0.091** | -7.9R | No edge |
| Yahoo ES=F 1h | 2.4y | 203 | 33.0% | -0.083 | 88 | 30.7% | **-0.015** | -1.3R | No edge |
| Duka NQ CFD 5m | 5.4y | 776 | 27.8% | +0.106 | 333 | 24.0% | **+0.049** | +16.4R | SCRUTINIZE |
| Duka ES CFD 5m | 5.4y | 774 | 25.1% | -0.049 | 332 | 25.9% | **+0.115** | +38.1R | SCRUTINIZE |

**Scrutiny on positive Duka OOS results:** Both the NQ CFD and ES CFD show positive OOS.
Before treating this as an edge, the following checks were performed:

1. **Look-ahead audit (PASSED):** Pool (prior-session H/L) is always built from the 
   previous calendar day's session, and the last bar of that pool occurs hours before 
   the first bar of today's trading window. No overlap found in 50 sampled cycles.

2. **Statistical significance (FAILED):** t-statistic for NQ CFD OOS = 0.52 (need > 2.0 
   for p < 0.05). Even at n=333 trades, the high standard deviation of the skewed R 
   distribution (occasional 5-9R wins) makes the mean unreliable at this magnitude.

3. **Time-stability (FAILED — critical):** Splitting the OOS into thirds reveals severe decay:
   - NQ CFD: 1st third (Oct–Dec 2024) = +0.47R | 2nd third (Jan–Mar 2025) = +0.01R | 3rd third (Apr–May 2026) = **-0.34R**
   - ES CFD: 1st third = +0.19R | 2nd third = +0.35R | 3rd third = **-0.20R**
   
   The most-recent 4-month window is negative on both instruments. An edge that decays
   to negative in its most-recent period is not a live edge — it's a regime artefact.

4. **IS→OOS consistency:** IS was strongly positive on NQ CFD (+0.106) and near-flat 
   on ES CFD (-0.049). The ES showing a negative IS and positive OOS is an IS/OOS flip,
   which is a red flag for data snooping or regime luck.

**Verdict on TJR futures:** No validated OOS edge. The apparent positive signal in the 
Dukascopy 5m data is not statistically significant (t=0.52), is concentrated in a 
historical period that ended before 2025, and is negative in the most-recent regime.

---

### B. ICT Sweep-Reversal (adapted from `ict_sweep.py`, no RTH filter)

Opening-range sweep and fade on full-session futures bars. OR=20m at 5m resolution.

| Dataset | Span | IS n | IS expR | OOS n | OOS expR | OOS totalR | Verdict |
|---------|------|------|---------|-------|----------|-----------|---------|
| Yahoo NQ=F 1h | 2.4y | 394 | -0.323 | 169 | **-0.208** | -35.1R | No edge |
| Yahoo ES=F 1h | 2.4y | 399 | -0.357 | 172 | **-0.421** | -72.4R | No edge |
| Duka NQ CFD 5m | 5.4y | 1094 | -1.156 | 470 | **-1.221** | -573.8R | No edge |
| Duka ES CFD 5m | 5.4y | 1100 | -1.918 | 472 | **-1.944** | -917.8R | No edge |

The Dukascopy 5m results show extreme negative expectancy — the ICT sweep-reversal 
fades the opening-range breakout, but on the full 23h futures session the "opening 
range" isn't a meaningful concept the same way it is at the RTH open. At 1h resolution 
on Yahoo futures the result is merely negative, not catastrophic, but still no edge.

---

### C. ORB — Opening Range Breakout (`orb_oos.py`, RTH bars only for futures)

Futures also trade RTH; the ORB is evaluated on RTH bars only (RTH open = real 9:30 ET).

| Dataset | Span | IS n | IS gross | IS net | OOS n | OOS gross | OOS net | Verdict |
|---------|------|------|---------|--------|-------|----------|--------|---------|
| Yahoo NQ=F 1h | 2.4y | 261 | +0.001 | -0.040 | 113 | +0.050 | **+0.010** | Too small |
| Yahoo ES=F 1h | 2.4y | 268 | +0.018 | -0.043 | 116 | -0.025 | **-0.080** | No edge |
| Duka NQ CFD 5m | 5.4y | 664 | +0.127 | +0.069 | 285 | +0.029 | **-0.032** | No edge |
| Duka ES CFD 5m | 5.4y | 702 | +0.083 | -0.015 | 301 | -0.050 | **-0.155** | No edge |

NQ 1h OOS shows +0.010 net but at n=113 and only 2.4y, this is noise-level. The deep 
5m Dukascopy test (n=285, 5.4y) shows the IS gross edge (+0.127) does NOT survive into 
OOS, a classic in-sample overfitting pattern.

---

### D. RSI2 / Trend (engine.py, session="all", futures 1h Yahoo)

Small trade count (n=24-56) — interpret with extreme caution.

| Dataset | Strategy | IS n | IS expR | OOS n | OOS expR | Verdict |
|---------|----------|------|---------|-------|----------|---------|
| Yahoo NQ=F 1h | RSI2 | 56 | +0.256 | 25 | **-0.155** | No edge |
| Yahoo NQ=F 1h | Trend | 56 | +0.127 | 25 | **+0.002** | Noise (t≈0) |
| Yahoo ES=F 1h | RSI2 | 56 | -0.211 | 24 | **+0.375** | IS/OOS flip — noise |
| Yahoo ES=F 1h | Trend | 56 | -0.187 | 24 | **+0.455** | IS/OOS flip — t=1.81 <2 |

ES Trend OOS looks impressive (+0.455R) but: (a) n=24 gives t=1.81, below the p<0.05 
threshold; (b) IS was -0.19R — an IS/OOS sign flip is a hallmark of regime luck or 
insufficient data, not a real edge; (c) the same strategy lost on SPY/QQQ.

---

## Buy-Hold Benchmark (OOS Window, Context Only)

| Instrument | OOS window | Buy-hold return |
|-----------|-----------|----------------|
| NQ=F Yahoo | ~8 months (2025-09 → 2026-05) | +28.1% |
| ES=F Yahoo | ~8 months (2025-09 → 2026-05) | +18.6% |
| NQ CFD Duka | ~20 months (2024-10 → 2026-05) | +51.0% |
| ES CFD Duka | ~20 months (2024-10 → 2026-05) | +32.0% |

These are unreachable in a funded intraday account (no overnight holds), printed for 
context only. An intraday system that cannot beat buy-hold is expected; the real bar 
is positive expectancy after fees on the intraday trades themselves.

---

## Honest Verdict

**Does using the REAL instrument and REAL 24h sessions change the conclusion?**

No. Every model that was dead on SPY/QQQ proxies is equally dead on the actual NQ/ES
futures and their Dukascopy index-CFD analogues, across 2.4–5.4 years of data:

- **TJR session-liquidity + FVG:** Negative OOS on Yahoo NQ/ES. Superficially positive 
  on Dukascopy 5m (NQ: +0.049R, ES: +0.115R) but NOT statistically significant (t<0.6), 
  NOT stable over time (most-recent 4 months: negative on both), and involves a skewed 
  R distribution where occasional large wins mask a 74–76% loss rate.

- **ICT sweep-reversal:** Consistently negative OOS across all instruments and timeframes. 
  On the deep 5m data the losses are severe (-1.2R/trade on NQ, -1.9R/trade on ES).

- **ORB:** Gross edge exists in-sample on the NQ CFD 5m (+0.127R) but does NOT survive 
  into OOS (−0.032R net). Consistent with every prior ORB test in this repo.

- **RSI2/Trend:** Trade counts too small for significance. IS/OOS sign flips on ES suggest 
  regime noise, not edge.

**Key finding on the "SPY vs futures" gap:** The hypothesis was that SPY/QQQ proxies 
miss the real overnight sessions and liquidity pools that TJR/ICT models are designed for.
This has now been tested directly. The conclusion is unchanged: the models produce no 
validated, statistically significant, time-stable positive expectancy after fees on the 
actual instruments. The overnight-session data did not reveal a hidden edge.

**What passed funded evaluation historically is risk discipline and position sizing**, not 
a signal entry that consistently beats fees after transaction costs. No mechanical model 
tested in this repo — on stocks, ETFs, or futures — has cleared that bar out-of-sample.

---

## New Files Created

| File | Description |
|------|-------------|
| `futures_fetch.py` | Fetches all 8 datasets (Yahoo + Dukascopy, batched) |
| `tjr_futures.py` | TJR/ICT model with real ICT session pools (Asia/London/NY) |
| `nqf_1h_730d.csv` | Yahoo NQ=F 1h, 2.4y |
| `esf_1h_730d.csv` | Yahoo ES=F 1h, 2.4y |
| `nqf_5m_60d.csv` | Yahoo NQ=F 5m, 2 months (sanity only) |
| `esf_5m_60d.csv` | Yahoo ES=F 5m, 2 months (sanity only) |
| `nq_cfd_5m_duka.csv` | Dukascopy E_NQ-100 5m, 5.4y (main deep test) |
| `es_cfd_5m_duka.csv` | Dukascopy E_SandP-500 5m, 5.4y (main deep test) |
| `nq_cfd_1h_duka.csv` | Dukascopy E_NQ-100 1h, 5.4y |
| `es_cfd_1h_duka.csv` | Dukascopy E_SandP-500 1h, 5.4y |
| `FUTURES_FINDINGS.md` | This file |
