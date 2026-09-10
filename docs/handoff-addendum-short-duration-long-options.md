# Handoff Addendum — Pivot to Short-Duration Single-Leg Long Options

**Prepared:** September 10, 2026
**Applies on top of:** `options-strategy-handoff.md` (the original credit-spread handoff)
**How to use this doc:** Each item below references the original document's section number. "WAS" is what the original said; "NOW" is the replacement; "WHY" is the reasoning; confidence tags use the same [VERIFIED] / [CONVENTION] / [SPECULATIVE] key as the original. Anything not mentioned here is unchanged — carry it forward as-is.

---

## What triggered this pivot

Confirmed via sourced research that multi-leg spreads require a margin account (Wealthsimple's spread-trading documentation; Webull's Level 3 approval tier per a TradeAlgo review), and that FINRA Rule 4210 sets a **hard $2,000 minimum equity requirement** to open a margin account at all — a regulatory floor, not a broker preference. This means the *real* <$1,000 account could never trade spreads under any broker, independent of the $3,000 paper target. Single-leg long options carry no such requirement (FINRA explicitly excludes full-cash option purchases from margin-equity rules), making them the only structurally available path for the real account, and the chosen path going forward for the paper build too.

---

## Section-by-section changes

### Section 1 — Summary
**WAS:** Multi-underlying credit spreads, 30–45 DTE (up to 90 in low IV), 1–5% sizing.
**NOW:** Single-leg long puts/calls, short duration (days, within the original <1-week goal this whole project started from), 1–5% sizing retained. Margin account no longer required.
**WHY:** Margin-account discovery above. [VERIFIED]

### Section 2 — Account & Platform
**CHANGE:** Margin account is no longer a requirement for this structure. This means the strategy is now theoretically compatible with the real <$1,000 account too (not just the $3,000 paper target) — though the sizing/delta trade-offs below still apply at that smaller size. Webull paperTrade remains the platform; Level 2 approval (long calls/puts) is what's needed, not Level 3. [VERIFIED — approval tiering per TradeAlgo's Webull review]

### Section 4 — Underlying Watchlist
**CHANGE — SPY likely priced out for this structure.** Spread risk (width − credit) doesn't scale with share price the way full option premium does. A single-leg put we checked on SPY near a reasonable delta cost **over $6,000 per contract** — nowhere close to a $3,000 account's budget, let alone $1,000. IWM (~$288/share) is the only underlying we've confirmed works at this budget. **GLD, TLT, and XLE are untested for single-leg pricing** — don't assume they carry over from the spread watchlist; their premiums need to be checked independently before use. [VERIFIED for SPY/IWM — pulled from live chains; SPECULATIVE/UNTESTED for GLD/TLT/XLE]

### Section 5 — Daily Entry Checklist
| Row | WAS | NOW | Why |
|---|---|---|---|
| 2 (IV Rank) | IV Rank ≥ ~50 favors selling | **IV Rank should be LOW** to favor buying premium | This is the *other branch* of the same already-sourced Option Alpha rule (step 4) — not a new claim, just switching which condition applies. [VERIFIED] |
| 3 (Strike selection) | 14–30 delta short strike targeting 70–90% POP | **No sourced delta target exists for buying short-duration options.** Recommend treating delta as a ranking criterion, not a hard threshold: among strikes that pass the budget check (row 4), pick the highest available \|delta\|, rather than asserting a specific cutoff number. | Option Alpha's POP framework is built for the *sold* leg's probability of finishing OTM — it doesn't have a stated analog for a purchased directional option. Asserting a specific delta target here would be fabricating precision we don't have. [explicitly UNRESOLVED — flagged rather than guessed] |
| 4 (Sizing) | `(width − credit) × 100` | **`premium_paid × 100`** — max loss on a long option is simply what you paid, no width term | Structural simplification, not a judgment call — long options don't have a spread width. [VERIFIED — standard options mechanics] |
| 6 (Events) | Awareness only, to avoid *surprising* a seller | Same awareness, but now potentially **the reason you're entering** | For a short-duration directional buyer, a scheduled catalyst can be the setup itself rather than just a risk to monitor — this reopens relevance of a rule considered early in this project (a scalping framework's "only trade with a catalyst" rule, sourced from TradeAlgo) that had been set aside. [SPECULATIVE — single practitioner source, not independently backtested] |

**Important distinction:** this pivot revives the *short duration* from the very first version of this project, but **not** the RSI/VWAP/volume indicators that version used. Those were set aside because Option Alpha's own research suggested short-term technical oscillators broadly underperform. The selection method here (IV Rank + budget-fit + delta-ranking) is different from, not a return to, that earlier rejected approach — don't let the shared "short duration" framing blur the two.

### Section 6 — Exit Rules
| Row | WAS | NOW | Why |
|---|---|---|---|
| 7 (Profit target) | ~50% of max profit (credit-based) | **~50–100% gain on premium paid** | Credit-based framing doesn't apply to a long option. This restores the framing from the very first version of this checklist. [SPECULATIVE — convention, not backtested] |
| 8 (Stop loss) | ~2× credit received | **~40–50% loss of premium paid, no exceptions** | Same reasoning — restores the original framing. [SPECULATIVE — convention, not backtested] |
| 9 (Time stop) | ~21 DTE (gamma-risk rule for sellers) | **Flatten by expiration regardless of P/L** — and since expiration is now only days out from entry, this largely collapses into "exit by end of the week" | The 21-DTE rule is specifically about a *seller's* late-cycle gamma exposure; it has no clean analog for a buyer who entered with only days of life left on the contract to begin with. [SPECULATIVE — adapted, not sourced] |

### Section 7 — Position Sizing Formula
**Replace the pseudocode block with:**
```
cost_per_contract = long_leg_ask * 100
cost_pct = cost_per_contract / current_account_balance

# Search all strikes on the correct side (put for bearish, call for bullish)
# near the money, within the target short-duration expiration.
candidates = [s for s in chain if s.cost_pct <= 0.05 and s.bid_ask_spread <= max(0.05, 0.05*s.price)]

IF candidates is empty:
  SKIP the day
ELSE:
  select the candidate with the highest abs(delta)  # no sourced floor — rank, don't gate
```
**Calibration data (IWM, Sep 14 2026 expiry, 4 DTE, spot ~$289.44) — for reference, not as fixed rules:**

| Sizing used | Strike found | Cost | Delta |
|---|---|---|---|
| ~1% of $3,000 (~$30 ceiling) | 282 put | $43 (slightly over 1%, ~1.4%) | ~12.5% |
| ~5% of $3,000 (~$150 ceiling) | 287 put | $126 (~4.2%) | ~32% |

**Note the mechanical relationship this reveals:** the sizing percentage you choose doesn't just control risk — at this structure, it directly controls what delta (and therefore what quality of directional exposure) is even reachable. Tighter sizing doesn't just mean "smaller loss if wrong," it also means "weaker, more lottery-like bet if right." This wasn't visible in the spread-based version of the system, where sizing and POP were set somewhat independently (rows 2/3 vs row 4).

### Section 8 — Worked Examples
**New example, replacing the spread-based ones for this structure (spread examples remain valid for reference if a margin account is opened later):**

IWM, Sep 14, 2026 expiration (4 DTE at time of pull), spot ~$289.44:
- Long 287 put, ask $1.26 → cost $126/contract, delta ≈ −0.3209
- Against $3,000: 126/3000 = **4.2%**, within the 1–5% band
- Max loss if the position goes to zero: exactly $126 (no further downside beyond premium paid)

### Section 9 — Rejected/Superseded Alternatives
**Item 3 ("Single-leg long puts/calls... rejected in favor of growing the account to $3,000") is REVERSED.** It's no longer rejected — it's the active structure, specifically because growing the account solved the *sizing* problem for spreads but not the newly-discovered *margin-eligibility* problem, which single-leg options sidestep entirely.
**Item 4 (>50% sizing rejected in favor of 1–5%) still stands unchanged** — this pivot doesn't touch position sizing philosophy, only structure.

### Section 10 — Known Gaps (additions)
- **No sourced delta target for buying short-duration options** (see Section 5, row 3 above) — this is a genuine open question, not just an unverified number.
- **SPY appears incompatible with this structure at this budget** — confirmed expensive, not yet fully ruled out at every possible strike/expiration combination, but nothing close to affordable has been found.
- **GLD, TLT, XLE untested for single-leg premium levels** — do not assume they transfer from the spread watchlist.
- **The $2,000 FINRA margin minimum** is now documented context for *why* the real account was structurally blocked from spreads — worth keeping in the record even though it no longer blocks the current (single-leg) path.

### Section 11 — Sources (additions)
- Wealthsimple — margin/spread account requirements documentation [VERIFIED]
- FINRA Rule 4210 / FINRA.org margin regulation pages — $2,000 minimum equity for margin accounts [VERIFIED]
- TradeAlgo — Webull options approval-level tiering (Level 1/2/3 breakdown) [single source, already cited once in the original handoff for a different claim]

---

*End of addendum. Everything in the original handoff not addressed above — the confidence-tagging system, the 1–5% sizing philosophy, the liquidity rule, the skip-the-day rule, the correlation caveat — carries forward unchanged.*
