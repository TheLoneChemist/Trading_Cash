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

## 2026-09-11 — Fixed scheduler running twice per container (duplicate billed API calls)
**Source:** user-provided Railway deploy log, read closely after the gate-message fix
above — the log showed the full scheduler-startup sequence appearing twice in one
container boot, once before gunicorn's own "Starting gunicorn" banner even printed.
**Changed:**
- Root cause: `app.py` started the scheduler via a module-level `else: start_scheduler()`
  side effect, which runs whenever the module is imported outside `__main__`. Under
  gunicorn this module gets imported in more than one process context (gunicorn's
  master process resolving `app:app`, and separately each worker process after
  forking) — both imports ran the side effect, producing two independent live
  `BackgroundScheduler` instances in the same container.
- Impact: every recurring job fired twice — including the weekly review's real,
  billed Anthropic API call, and the daily Tradier chain pulls. This had been true
  since the weekly-review feature was added; no way to retroactively know how many
  extra Anthropic calls were made without checking usage on console.anthropic.com.
- Fix: removed the module-level `else:` side effect entirely. Added
  `gunicorn.conf.py` with a `post_fork` server hook, which gunicorn guarantees runs
  exactly once per actual worker process and never in the master. Updated the
  `Procfile` to pass `--config gunicorn.conf.py`.
- Verified by actually running gunicorn locally (not just reasoning about it) and
  confirming "Startup catch-up" — the unambiguous single-execution marker — now
  appears exactly once per boot, in the correct order after gunicorn's own banner.
**Why:** a duplicated scheduled job is a silent, recurring cost — worth catching
immediately rather than letting it compound weekly. Recommend checking
console.anthropic.com's usage page for any doubled charges since the review feature
was deployed.

## 2026-09-11 — Fixed stale gate message + scheduler skip after restart
**Source:** user report ("the app has the wrong time") with a screenshot showing the
dashboard displaying "It's 05:45 AM EDT — waiting until 9:45 AM ET" at 9:48 AM actual
local time.
**Changed:**
- Root cause: `app.py`'s dashboard route only ever displayed the `gate_reason` string
  stored in `data/suggestions.json` from whenever `run_daily_job()` last actually ran
  — not a live clock. If the scheduler's daily job hadn't fired yet today (see next
  bullet), that stale sentence would sit on the page indefinitely.
- Actual trigger: APScheduler's `CronTrigger` computes its next fire time from
  whenever the scheduler process starts. A Railway container restart any time after
  9:45 AM ET on a trading day caused the trigger to skip straight to *tomorrow's*
  9:45 AM, silently never running today at all.
- Fix: `dashboard()` now also computes the gate status live via
  `market_calendar.can_run_now()` on every page load, and compares the stored
  `generated_at` against today's ET date before trusting it as "current" — a stale
  success/waiting message can no longer masquerade as live data.
- Fix: `start_scheduler()` now does a one-time startup catch-up check — if the app
  starts past today's 9:45 AM gate and no run has been recorded yet today, it runs
  `run_daily_job()` immediately instead of waiting for tomorrow.
**Why:** the confusion wasn't a timezone math bug (`datetime.now(pytz_tz)` was
verified correct) — it was stale cached state being displayed as if it were live,
compounded by a scheduler gap that could leave that stale state in place all day.

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
