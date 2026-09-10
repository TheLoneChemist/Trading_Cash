# Multi-Underlying Options Credit Spread Strategy — Automation Handoff

**Prepared:** September 10, 2026
**Purpose:** This document is a complete, self-contained handoff of a rules-based options strategy developed through iterative research and live chain testing. It's meant to be handed to another AI session to build automation around. It is not financial advice — it's a record of a specific rule set, its sourcing, its confidence levels, and its unresolved gaps.

---

## 1. Summary

A mechanical, multi-underlying **credit spread (premium-selling)** strategy adapted from Option Alpha's publicly published "7-Step Entry Checklist." Trades are vertical put/call credit spreads, 30–45 days to expiration (extendable to 60–90 in low-IV conditions), sized at 1–5% max risk per trade. The strategy was stress-tested against five live option chain pulls during development; those tests forced a change in account size (from <$1,000 to a $3,000 paper account) because the original account size could not mechanically fit real trades within the sizing rule. **Skipping a trading day with no qualifying setup is an explicit, accepted outcome, not a failure state.**

---

## 2. Account & Platform

| Item | Value |
|---|---|
| Real account size | <$1,000 (user's actual live account) |
| Paper practice target | **$3,000** — chosen specifically because it's the minimum size at which real chain data showed standard $1-wide spreads fitting inside 1–5% sizing at genuine 70–90% POP deltas |
| Paper platform | **Webull paperTrade** |
| Platform capabilities confirmed | Supports options including multi-leg spreads; spread orders execute as a single unit (eliminates leg-in/leg-out fill risk) |
| Platform caveat | [SINGLE-SOURCE, UNVERIFIED] One broker-review source (tradealgo.com) states Webull's paper simulator fills at **mid-price**, potentially overstating real-world performance by **5–15%** vs. actual bid/ask fills. Treat paper results as optimistic. |
| Platform default balance | Webull paperTrade defaults to **$1,000,000** virtual capital. This must be manually overridden in practice — size every trade against the **$3,000 target**, not the account's literal balance, unless Webull's interface allows setting a custom starting balance (unconfirmed at time of writing). |
| Why not TradingView | TradingView's native Paper Trading engine simulates the *underlying only* (stocks/futures/forex/crypto), not options contracts. Pine Script strategies run against underlying OHLCV price series and cannot model option chains, strikes, bid/ask, or Greeks — a Pine Script "strategy" would not actually be testing this system. |

---

## 3. Source Basis & Confidence Key

Every rule below is tagged with how well-sourced it is. **This tagging is load-bearing for automation — don't silently promote a [CONVENTION] or [SPECULATIVE] rule to the same trust level as a [VERIFIED] one.**

- **[VERIFIED]** — Directly confirmed either by fetching the primary source or by pulling live/real option chain data during this conversation.
- **[CONVENTION]** — Widely-cited industry practice, but not independently backtested by us for this specific strategy/timeframe/underlying combination.
- **[SPECULATIVE / SINGLE-SOURCE]** — Came from one unverified source (informal blog, forum post, or secondhand summary of paywalled content). Treat as a hypothesis to test in paper trading, not a confirmed edge.

---

## 4. Underlying Watchlist

| Ticker | Asset class | Rationale | Confidence |
|---|---|---|---|
| **SPY** | Broad equity | Deepest options liquidity of any US ETF; penny-wide spreads | [VERIFIED] — ETF.com liquid-options data; confirmed live on-chain |
| **IWM** | Small-cap equity | High liquidity, higher IV than SPY → fatter premiums | [VERIFIED] — confirmed live on-chain; IV characterization per ApexVol |
| **GLD** | Gold/commodity | Named as "uncorrelated to stocks" with solid options liquidity | [SPECULATIVE] — ApexVol source; **correlation is regime-dependent**, not fixed (a 2010-era source showed stock-commodity correlation spiking to ~0.80 during stressed macro periods) |
| **TLT** | Long bonds | Named in a diversification-focused ETF list alongside GLD/XLE | [SPECULATIVE] — same correlation caveat applies (~0.90 stock-bond correlation observed in some historical periods) |
| **XLE** | Energy sector | Distinct sector driver (oil/rates) vs. broad index | [VERIFIED liquidity / SPECULATIVE diversification benefit] |

**Known limitation:** SPY and IWM are both broad equity and will often move together — true diversification across this watchlist is partial, not complete. Do not assume beta-neutrality without checking live correlation.

---

## 5. Daily Entry Checklist

| # | Rule | Threshold | Confidence | Source |
|---|---|---|---|---|
| 1 | **Liquidity gate** | Bid-ask spread ≤ $0.05, or ≤5% of the option's price | [VERIFIED] | Option Alpha 7-Step Checklist (step 2); corroborated by ETF.com SPY spread data |
| 2 | **IV Rank filter** | IV Rank ≥ ~50 favors credit spreads (selling structure); low IV Rank favors buying premium instead | [VERIFIED — concept / CONVENTION — exact "50" threshold] | Option Alpha 7-Step Checklist (steps 3–4) |
| 3 | **Strike selection by delta** | Short strike at ~14–30 delta (≈70–90% probability of profit) | [VERIFIED] | Option Alpha 7-Step Checklist (step 5) |
| 4 | **Position sizing / fit check** | `Max risk = (strike width − credit received) × 100`. Accept only if this is 1–5% of **current** account balance (not a fixed number — recompute every time balance changes). **If nothing on the chain satisfies both this and rule 3's delta target, skip the day.** | [VERIFIED — formula and threshold both confirmed against 5 live chain pulls] | Option Alpha step 6; account-size math independently verified live in this conversation |
| 5 | **Portfolio fit / correlation check** | If holding multiple open positions, check they aren't all stacked in the same direction on highly correlated underlyings | [VERIFIED — concept / open gap — no live correlation check performed yet] | Option Alpha 7-Step Checklist (step 1) |
| 6 | **Upcoming events check** | Know FOMC/CPI/jobs-report dates falling inside the intended hold window before entering | [VERIFIED] | Option Alpha 7-Step Checklist (step 7) |

**Always use the real bid to calculate credit received, never ask.** An early pass in this conversation used ask-only pricing as a stand-in when bid wasn't visible on-screen; when real bid data was later obtained, actual credit was lower and max risk higher than the ask-only estimate. Ask-only pricing is optimistic and should never be used for a live sizing decision.

---

## 6. Exit Rules

| # | Rule | Threshold | Confidence |
|---|---|---|---|
| 7 | **Profit target** | Close at ~50% of max profit | [CONVENTION] — standard premium-selling practice, not independently backtested for this setup |
| 8 | **Stop loss** | Close at ~2× credit received as a loss (risking roughly double what was collected) | [SPECULATIVE] — reasonable default, unverified multiplier |
| 9 | **Time stop** | Close or roll by ~21 days to expiration ("21 DTE rule") to avoid accelerating gamma risk | [SPECULATIVE] — commonly cited in options-selling education, not independently verified here |

**Recommendation:** paper-trade rows 7–9 explicitly as hypotheses. They are the least-verified part of the system.

---

## 7. Position Sizing Formula (for automation)

```
credit = short_leg_bid - long_leg_ask
max_risk_per_contract = (strike_width - credit) * 100
max_risk_pct = max_risk_per_contract / current_account_balance

IF max_risk_pct is between 0.01 and 0.05 (target ~0.02-0.03 as a comfortable mid-band)
  AND short_leg_delta is between 0.14 and 0.30 (absolute value)
  AND bid_ask_spread <= max(0.05, 0.05 * option_price)
  AND iv_rank >= ~50
THEN candidate trade is valid
ELSE skip
```

**Open gap:** this conversation never obtained a true IV Rank (percentile of IV over its own historical range) — only a raw IV% reading was visible on one screenshot (17.66%). IV Rank requires historical IV data (e.g., 1-year lookback) that a live screenshot doesn't show. **Automation needs a historical-IV data source to compute this — raw IV alone is not IV Rank and should not be substituted for it.**

---

## 8. Worked Examples (real chain data, dated — do not treat as current)

All data below was pulled live during this conversation on **September 10, 2026**. Treat as frozen historical examples for calibration/testing, not live prices.

**SPY — Oct 16, 2026 expiration (36 DTE), spot ~$757.62:**
- Short 736 put (bid $7.19, delta −0.2817) / Long 735 put (ask $7.05, delta −0.2745)
- Credit = $0.14 → Max risk = (1.00 − 0.14) × 100 = **$86**
- Against $3,000 account: 86/3000 = **2.87%** → passes rule 4

**IWM — Oct 16, 2026 expiration (36 DTE), spot ~$288.03–288.90:**
- Short 273 put (bid $2.81, delta −0.2244) / Long 272 put (ask $2.68, delta −0.2124)
- Credit = $0.13 → Max risk = (1.00 − 0.13) × 100 = **$87**
- Against $3,000 account: 87/3000 = **2.9%** → passes rule 4

Both examples sit comfortably mid-band (not scraping the 5% ceiling), which is the intended target — a trade that only barely clears 5% leaves no room for the underlying to move against the position before max loss.

---

## 9. Explored and Rejected Alternatives (context for why these aren't in the final system)

1. **RSI(14) / VWAP-cross / Volume-multiple short-duration (<1 week) directional system.** This was the starting point. Abandoned after finding that Option Alpha's own large-scale backtesting research (secondhand summary of their paywalled "SIGNALS" report, plus their general TA content) argues most technical indicators are not profitable/predictive, and that the indicators which did work in their testing were long-term, not short-duration. **[SPECULATIVE — could not independently verify the SIGNALS report's actual contents; report link is optionalpha.com/show40, access not confirmed.]**
2. **Opening Range Breakout (ORB), price-action based.** A real, disclosed backtest exists (Options.cafe: 303 trades, Feb 2024–Mar 2026 on 0DTE SPY, with disclosed spread-drag and no-commission caveats). Not pursued further once the strategy pivoted toward Option Alpha's spread-based system, but remains a legitimate, separately-sourced fallback if the credit-spread approach stalls.
3. **Single-leg long puts/calls to solve the <$1,000 sizing problem.** Tested live: at 36 DTE, strikes cheap enough to fit a $10–50 budget had delta collapsed to ~1–3% (lottery-ticket territory, not a real directional bet). At 4 DTE, a genuinely usable ~10–13% delta became affordable — but this reintroduces near-0DTE gamma/theta risk and abandons the 30–90 day probability-of-profit framework the rest of the system is built on. **Rejected in favor of growing the account to $3,000 instead**, which allows the spread-based system to run as originally designed.
4. **>50% per-trade position sizing.** Original stated risk tolerance. Explicitly abandoned in favor of Option Alpha's 1–5% sizing once it became clear the two aren't separable — their probability-of-profit math and portfolio-fit logic assume many small positions surviving inevitable losers, not one oversized bet.

---

## 10. Known Gaps for the Automation Builder to Resolve

- **IV Rank data source not established.** Need historical IV (not just spot IV) to compute rank/percentile per rule 2.
- **Correlation check (rule 5) is conceptual only** — no live correlation data has been pulled for SPY/IWM/GLD/TLT/XLE. Automation should compute this dynamically rather than assuming static diversification.
- **Exit rules (7–9) are unverified conventions.** Recommend the automation log paper-trade outcomes specifically to test these percentages before they're trusted with real capital.
- **Webull's mid-price paper fill assumption** should be corrected for (e.g., simulate a fill at bid+small slippage instead of mid) if paper results are going to inform real-money decisions later.
- **Account balance for sizing must be dynamic**, not hardcoded to $3,000 — it should recompute against actual current paper balance as trades open/close.
- **Strike width isn't always $1.** The formula in Section 7 is width-agnostic and should be, since some underlyings/strikes may offer $0.50 or wider increments — confirm per-chain rather than assuming $1.

---

## 11. Sources Referenced in This Handoff

- Option Alpha — 7-Step Entry Checklist: `optionalpha.com/lessons/7-step-entry-checklist` [VERIFIED, fetched directly]
- Option Alpha — SIGNALS report: `optionalpha.com/show40` [NOT independently verified — paywalled, secondhand summary only]
- Options.cafe — ORB backtest (0DTE SPY) [referenced, not fetched directly]
- ETF.com — "ETFs With The Most Liquid Options" [VERIFIED]
- ApexVol — "Best ETFs for Options Trading" [single source]
- OptionsTradingIQ — "10 Best ETFs for Iron Condors" [single source]
- SteadyOptions — SPX vs SPY vs XSP liquidity comparison [single source]
- TradeAlgo — Webull options/paper-trading review [single source, includes the mid-price-fill claim]
- tastylive (tastytrade) — general options research/education, mentioned as a paper-trading alternative

---

*End of handoff. This document reflects the state of the strategy as of the conversation it was generated from, and should be treated as a starting point for automation, not a finished, backtested system.*
