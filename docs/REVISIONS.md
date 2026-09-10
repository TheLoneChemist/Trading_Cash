# Revisions Log

Tracks changes made to this tool's strategy logic and code, so a future weekly review
(`src/weekly_review.py`) and any new Claude chat session picking up a handoff prompt
have context on what's already been tried — instead of re-discovering or re-suggesting
the same fix twice.

**This file is git-tracked, not runtime-generated.** The live app only *reads* it
(weekly_review.py includes it in the context sent to Claude for analysis); it never
writes to it, since anything written only to the Railway filesystem would vanish on
the next redeploy without ever making it back into the repo. Entries are added by
whoever (or whichever Claude session) actually makes a change — see the format below.

## Format

Each entry:

```
## YYYY-MM-DD — Short title
**Source:** what prompted this (e.g. "weekly review 2026-09-14", "manual addendum",
    "user request in chat")
**Changed:** bullet list of the actual code/behavior changes, specific enough that a
    future reader doesn't have to go read the diff to know what happened
**Why:** one or two sentences of rationale
```

Newest entries at the top. Don't delete old entries — the point is the history.

---

## 2026-09-10 — Pivot to short-duration single-leg long options
**Source:** `docs/handoff-addendum-short-duration-long-options.md`
**Changed:**
- Replaced the active strategy from multi-leg credit spreads to single-leg long
  puts/calls throughout `src/strategy.py`, `src/sizing.py`, `src/daily_job.py`,
  `templates/dashboard.html`, and `templates/history.html`.
- Original spread logic preserved as `legacy_*` functions / `LEGACY_*` config
  constants rather than deleted, in case a margin account is opened later.
- Corrected the order-ticket UI to say "Single Option" instead of "Vertical" —
  this was the single most safety-critical change, since the earlier spread-era UI
  would have actively told the user to select the wrong strategy in Webull for the
  new structure.
- Changed logged-trade schema from two-leg (`short_strike`/`long_strike`/
  `spread_type`/`credit_received`) to single-leg (`option_type`/`strike`/
  `premium_paid`), with `premium_paid` defined as the per-contract total cost
  (matching Webull's own "Total Cost" column) rather than a $/share price, to avoid
  a repeat of an earlier unit-confusion incident.
**Why:** FINRA Rule 4210 sets a hard $2,000 minimum equity to open a margin account,
which multi-leg spreads require — this structurally blocked the real (<$1,000)
account from ever trading spreads, independent of the $3,000 paper target. Single-leg
long options carry no such requirement.

## 2026-09-10 — Added weekly Claude-powered review
**Source:** user request in chat
**Changed:**
- Added `src/weekly_review.py`: joins the week's suggestion history against the trade
  log in plain Python, then makes one Anthropic API call for analysis + a handoff
  prompt for a new Claude chat.
- Added `data/suggestion_history.json` (rolling log, written by `daily_job.py` on
  every run) since `data/suggestions.json` only ever held the latest day.
- Added the Review page (`templates/review.html`) and a Sunday 6 PM ET scheduler job.
- Added this file.
**Why:** to close the loop between what the tool suggests and what actually gets
executed — see the SPY $825 single-leg call trade earlier in the project's history,
which didn't match any suggestion the tool had generated.
