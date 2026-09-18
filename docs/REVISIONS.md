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

## 2026-09-18 — Fixed ambiguous close-price label causing a unit-mismatch bug
**Source:** user report of a P&L calculation that "looked wrong" — a $140 cost trade
closed for a claimed $138.34 loss on a $1.66 entry.
**Changed:**
- Root cause: the close-trade form's price field was labeled only "price/contract $"
  with no unit clarification, unlike the log-trade form's "Total cost per contract"
  field which explicitly warns it's not a $/share price. The user (reasonably) entered
  $1.66 — a per-share quote price, as Webull's "Last Price" column would show — where
  the form actually expected the per-contract total ($166.00). The underlying
  subtraction (`proceeds - cost`) was correct; the input itself was in the wrong unit.
- Fixed both the close form and the edit-close form in `templates/history.html` to
  explicitly say "Total $ per contract at close (not $/share)," matching the existing
  convention on the log-trade form.
- This was a labeling/UI fix only — no changes to `storage.py`'s close/edit-close
  logic, which was already computing correctly from whatever number it was given.
**Why:** this is the third or fourth time in this project a per-share vs. per-contract
mismatch has caused a real, wrong-looking number (see the original credit-spread
confusion and the SPY $825 single-option incident earlier in the history). Worth
treating as a pattern: any dollar input field in this app should say explicitly which
convention it expects, not just "$".

## 2026-09-15 — Diagnosed unreliable in-app scheduler; added Railway Cron backup
**Source:** user report of the same "05:45 AM EDT — waiting" message persisting
unchanged from Sept 11 through Sept 15, confirmed via Railway's Metrics tab showing
completely flat CPU and network activity for a full trading day (Sept 14, a Monday)
with no blip at 9:45 AM — the daily job's Tradier calls never happened that day.
**Changed:**
- No application code changed. This was diagnosed as the in-process APScheduler
  background thread not reliably surviving to 9:45 AM ET inside Railway's web
  service, for reasons not fully root-caused (possibly related to how the platform
  manages the container, not something visible from inside the app itself).
- `docs/DEPLOYMENT.md` Part 9 now recommends adding a Railway Cron Job that calls the
  existing `/refresh` route directly (reusing the app's own timezone-aware gate logic)
  as an independent, platform-native trigger — scheduled twice daily at both possible
  UTC offsets (13:50 and 14:50 UTC) so DST transitions never need manual updating; the
  app's own gate harmlessly no-ops on whichever call falls outside market hours. Same
  pattern recommended for the weekly review's `/review/run`.
- The in-app scheduler is kept running as free redundancy, just no longer trusted as
  the sole trigger.
**Why:** if the weekly review sees gaps in `suggestion_history.json` (missing trading
days with no entry at all, as opposed to a `skip_day` entry), this is the likely
explanation — a scheduling reliability gap, not a strategy or checklist problem. Don't
mistake missing history for "nothing qualified that day."

## 2026-09-11 — Trade log now supports scaling out, editing, and price-based closing
**Source:** user request in chat
**Changed:**
- Replaced the profit/loss-dropdown close form with a direct "contracts to close" +
  "price per contract at close" form — realized P&L is now computed from the actual
  numbers instead of asked as a manual judgment call.
- Trades now support multiple partial closes (scaling out): `src/storage.py`'s
  `add_close()` records each sell-to-close event separately; a trade stays "open"
  until all originally-bought contracts are accounted for. Over-closing (trying to
  close more than remain) is rejected with an explicit error rather than silently
  clamped.
- Added `edit_close()` and `delete_close()` to correct a wrong close entry, and
  `update_trade_fields()` to correct a trade's core fields (symbol, strike,
  expiration, contracts, premium paid, etc.) after the fact — covers "I saved the
  wrong info" for both what you bought and what you sold.
- `update_trade_fields()` rejects lowering `contracts` below what's already recorded
  as closed, rather than producing a negative remaining count.
- History page: open positions show "remaining / original" contracts plus a
  sub-listing of closes so far; closed positions show every close event and the net
  realized P&L, colored green/red.
**Why:** the previous single-shot "closed — profit/loss" model couldn't represent a
real position scaled out over multiple sells at different prices, and had no
correction path if a number was mis-entered.

## 2026-09-11 — Dashboard now shows the actual failure reason instead of guessing
**Source:** user report that the "may not have fired" message persisted even in a
fresh incognito window after the scheduler-duplication fix above.
**Changed:**
- The gate-status message for "market's open, but no suggestions yet" case
  previously always guessed "the scheduled run may not have fired today" — but a run
  can also execute successfully-as-in-completes and still not produce `ran: true`,
  most commonly because no account value is set. On Railway without a persistent
  Volume mounted at `/app/data` (see docs/DEPLOYMENT.md Part 5), every redeploy wipes
  `data/account_state.json` back to blank, so a freshly-redeployed app hits this
  every time regardless of whether the scheduler itself is healthy.
- `dashboard()` / `dashboard.html` now surface the actual stored `gate_reason` from
  today's attempt (if one exists) instead of a generic guess, and specifically call
  out the missing-Volume possibility when the account value is empty.
**Why:** the previous message actively pointed at the wrong root cause in this case,
sending troubleshooting effort toward "is the scheduler broken again" when the real
issue was an empty account value — expensive to debug remotely without seeing the
actual stored reason.

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
