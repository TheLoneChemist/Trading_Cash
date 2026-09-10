# Deployment guide

Written for someone who has basic Python experience but hasn't deployed a Flask app
to Railway before. Follow it top to bottom the first time.

## Part 1 — Get a Tradier API key

1. Go to https://tradier.com/individuals and sign up for a **developer sandbox**
   account (free — you don't need a funded brokerage account for this).
2. In the Tradier developer dashboard, find your **sandbox API access token**.
   Sandbox market data is delayed (typically 15 min) but that's fine for a morning
   dashboard you read before market-open decisions settle in — it is not fine if you
   later try to day-trade off it in real time.
3. Keep that token handy — you'll paste it into Railway as a variable, never into code.

## Part 2 — Push this repo to GitHub

1. If you don't have one, create a free GitHub account.
2. Create a new **private** repository (private, since this is your personal trading
   tool — nothing about it needs to be public).
3. From inside the unzipped `trading-dashboard/` folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```
   Double-check `.env` is **not** in what you committed (`.gitignore` already excludes
   it) — run `git status` and confirm you don't see `.env` listed.

## Part 3 — Create the Railway project

1. Go to https://railway.app and sign in (GitHub login is easiest).
2. **New Project → Deploy from GitHub repo** → pick the repo you just pushed.
3. Railway will detect the `Procfile` and Python project automatically (via Nixpacks)
   and start a first build. It will likely **fail** at this point — that's expected,
   because you haven't set the environment variables yet. Continue to Part 4.

## Part 4 — Set environment variables

In the Railway project, click your service → **Variables** tab → add these one at a
time (values, not the example placeholders):

| Variable | Value |
|---|---|
| `TRADIER_API_KEY` | the sandbox token from Part 1 |
| `TRADIER_ENV` | `sandbox` |
| `ADMIN_SECRET` | make up a long random string — treat it like a password |

Optional, for the weekly automated review (see Part 9 below):

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | an API key from console.anthropic.com (a real, billed key — different from a claude.ai subscription) |
| `ANTHROPIC_MODEL` | leave unset to use the default (`claude-sonnet-5`) |

You do **not** need to set `PORT` — Railway injects it automatically.

After saving, Railway auto-redeploys. Check the **Deployments** tab → open the latest
deploy → **View logs**. You should see lines ending in something like:
```
Scheduler started: daily job set for 9:45 AM ET, Mon-Fri.
```
That means it booted correctly.

## Part 5 — Attach a persistent Volume (important — don't skip)

Railway containers are **ephemeral**: every redeploy wipes the filesystem, which would
silently erase your trade log and account value. Fix this once:

1. In the service, go to the **Volumes** tab → **New Volume**.
2. Mount path: `/app/data`
3. Redeploy. From now on, everything written to `data/*.json` survives redeploys.

Confirm it worked: open the dashboard (Part 6), enter an account value, then manually
trigger a redeploy from the Railway dashboard, and check the value is still there
afterward.

## Part 6 — Get your dashboard URL

1. In the service, go to **Settings → Networking → Generate Domain**. Railway gives
   you a `*.up.railway.app` URL.
2. Open it. You should see the Trade Desk dashboard with an empty suggestions section
   and a form to enter your account value — enter your **paper account** target
   ($3,000 per the strategy handoff) as both account value and buying power to start.

This URL is unauthenticated by default — anyone with the link could view it (though
they can't place trades or see your broker credentials, since none live here). If that
bothers you, Railway's paid tiers support IP allowlisting, or you can put the whole app
behind Railway's built-in "Private Networking" and only access it via a VPN/tailnet —
that's beyond this guide's scope but worth knowing exists.

## Part 7 — Confirm the daily schedule is really running

The app schedules itself internally (APScheduler, see `app.py`) for **9:45 AM ET,
Monday–Friday** — no separate Railway cron setup needed for this default path. To
confirm it's wired correctly without waiting for tomorrow morning:

```bash
curl -X POST https://YOUR-APP.up.railway.app/refresh \
  -H "X-Admin-Secret: YOUR_ADMIN_SECRET"
```

- **Outside market hours or on a weekend/holiday**, you should get back JSON with
  `"ran": false` and a `gate_reason` explaining why — that's the gate working
  correctly, not a bug.
- **During market hours after 9:45 AM ET on a trading day**, you should get back
  `"ran": true` and a `candidates` array (possibly empty, if nothing qualifies —
  see the "skip day" note in the dashboard).

Never call `/refresh?force=1` against your live Railway deployment routinely — `force`
bypasses the market/time gate and exists only so you can test the strategy logic
locally without waiting for 9:45 AM. Using it in production defeats the whole point of
the gate.

### Alternative: Railway Cron Job service instead of the in-app scheduler

If you'd rather not have a scheduler running inside your always-on web process (e.g.
you want to scale to multiple web instances later, which would otherwise cause the job
to fire multiple times), you can disable the APScheduler block in `app.py` and instead:

1. In Railway, **New → Cron Job** (a separate lightweight service in the same project).
2. Command: `python scripts/run_daily.py`
3. Schedule: `45 13 * * 1-5` (this is UTC — 13:45 UTC = 9:45 AM ET during EDT; you'll
   need `44 14 * * 1-5` during EST months, or just leave the in-app scheduler running,
   which already handles the ET/UTC daylight-saving switch for you via `pytz`).
4. Make sure this Cron Job service has the same `TRADIER_API_KEY` / `TRADIER_ENV`
   variables and the same mounted Volume as the web service (Railway lets services
   within a project share a Volume).

For a first version, the in-app scheduler (Part 7's default) is simpler and handles
daylight saving automatically — only switch to this if you have a specific reason to.

## Part 8 — Daily use

Each weekday morning after 9:45 AM ET, open your Railway URL. Review the suggestions
and their checklists, decide for yourself, and if you place a trade in Webull
paperTrade, come back and log it in the "Log a trade you placed" form so your
performance history stays accurate.

---

## Part 9 — Weekly Claude-powered review (optional)

Once `ANTHROPIC_API_KEY` is set (Part 4), the app runs a review every Sunday evening
(6 PM ET) that:

1. Pulls the past 7 days of suggestion history (`data/suggestion_history.json`,
   written automatically by every daily run) and the trade log.
2. Joins them in plain Python — which trades matched a suggestion, which didn't,
   which suggestions were never acted on — before sending anything to Claude, so the
   API call is spent on interpretation, not data-wrangling.
3. Makes one call to the real Anthropic API (`api.anthropic.com`, not claude.ai) asking
   for a critique of the strategy's own code and, specifically, an explanation of any
   gap between what was suggested and what you actually executed.
4. Saves the result to `data/weekly_reviews.json` and shows it on the **Review** tab,
   ending with a ready-to-copy prompt for a **new** Claude chat.

**This costs real money per run** — unlike Tradier's free sandbox, `api.anthropic.com`
bills per token. At the summary sizes this produces (a few KB of JSON), a weekly run
should cost a few cents, but it's not free, which is also why the manual trigger on the
Review page asks for your `ADMIN_SECRET` before running.

**Using the output:** when a review finishes, re-zip this repo (with whatever changes
you've made since), start a brand-new Claude chat, attach the zip, and paste the
"Handoff prompt" text from the Review page. That new session has no memory of this
conversation — the prompt is written to give it everything it needs from the repo
alone, including specific file/function names to look at.

## Known gaps for a future automation pass

These are carried over from the strategy handoff's own "Known Gaps" section, translated
into what it'd take to close them in this codebase:

- **IV Rank is not computed.** `src/strategy.py::iv_rank_status()` always returns
  `MANUAL_REVIEW`. To fix: find a data source with historical IV percentile (Tradier's
  base plan doesn't expose this cleanly) — e.g. a paid market-data vendor, or compute it
  yourself by storing your own daily IV snapshots per symbol over time and calculating
  the percentile once you have ~1 year of history. Wire the result into
  `strategy.iv_rank_status()` and change its `status` logic from an unconditional
  `MANUAL_REVIEW` to a real `PASS`/`FAIL` against `config.IV_RANK_THRESHOLD`.
- **Correlation check (rule 5) is a same-group heuristic, not real correlation data.**
  `src/strategy.py::check_portfolio_fit()` only checks "same watchlist group, same
  direction." A real version would pull historical price series for open-position
  underlyings (Tradier's `/markets/history` endpoint, already wrapped in
  `tradier_client.get_history()`) and compute a rolling correlation coefficient.
- **Exit rules (profit target / stop loss / 21 DTE) are unverified conventions,
  computed but not enforced.** This app calculates and displays exit levels
  (`src/sizing.py::calculate_exit_levels`) when you log a trade, but doesn't monitor
  open positions intraday or alert you when a level is hit — it's a suggestion tool
  for entries, not a position-monitoring tool. Log paper-trade outcomes against these
  levels for a few months before trusting them with real capital, per the handoff.
- **Webull's mid-price paper fill assumption isn't corrected for.** If you later want
  paper results to better predict real fills, simulate a fill at bid + a small slippage
  buffer instead of trusting Webull's own paper mid-price fill when you manually decide
  whether a logged trade would have actually filled.
- **This app has no automated tests.** For a personal tool at this stage that's a
  reasonable trade-off, but if you extend the strategy logic, consider adding a
  `tests/` directory with `pytest` cases around `src/sizing.py` and `src/strategy.py`
  at minimum, since those are the modules where a silent math error would cost money.
