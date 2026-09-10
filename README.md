# Options Suggestion Dashboard

A personal, **suggest-and-log** tool for the options strategy described in
`docs/strategy-handoff.md` and its pivot in
`docs/handoff-addendum-short-duration-long-options.md`. It is **not** a trading bot.

**Active strategy (as of the Sept 10, 2026 addendum): short-duration single-leg long
options** — buying a single put or call, days to expiration, not a multi-leg spread.
The original multi-leg credit-spread design is preserved in the codebase as legacy
(clearly marked `LEGACY_*` in `config.py` and `legacy_*` in `strategy.py`/`sizing.py`)
in case a margin account gets opened later and spreads come back into play — see
`docs/strategy-handoff.md`. Why the pivot happened: multi-leg spreads require a margin
account, and FINRA Rule 4210 sets a hard $2,000 minimum equity to open one at all — a
regulatory floor that structurally blocked the original <$1,000 real account from ever
trading spreads, independent of the $3,000 paper target. Single-leg long options carry
no such requirement.

Every morning (market days only, never before 9:45 AM ET) it:

1. Pulls live option chain data from Tradier for your watchlist (SPY, IWM, GLD, TLT, XLE).
2. Runs the entry checklist against that data: liquidity, IV-Rank awareness (now
   favoring LOW IV since you're buying premium, not selling it), affordability-based
   sizing (cost per contract = your max loss, no width term), delta as a ranking
   factor only (no sourced threshold — see the addendum), portfolio-correlation
   heuristic, and upcoming-events awareness (now framed as a potential entry catalyst,
   not just a risk to flag before selling).
3. Writes the results to a small dashboard you open in a browser — clearly labeled as
   a **single-leg buy**, with Webull-specific guidance to keep the strategy dropdown on
   "Single Option," not "Vertical."

You review the dashboard, decide for yourself, and manually place any trade in Webull
(paper account first). The tool never touches a broker order endpoint. There is no
order-placement code anywhere in this repo, on purpose.

## What this is not

- **Not** financial advice, and not a validated/backtested system. The handoff doc this
  is built from is explicit that several of its rules (exit rules, GLD/TLT/XLE
  "diversification," IV Rank threshold) are conventions or single-source claims, not
  verified edges. The dashboard surfaces that uncertainty instead of hiding it.
- **Not** an auto-trader. `POST` routes exist only to (a) refresh the day's suggestions
  from market data and (b) let *you* log an account value or a trade *you* already placed.
- **Not** a finished IV Rank calculator. Tradier's basic market-data plan does not give a
  clean historical-IV percentile feed, so this ships with IV Rank explicitly marked
  "unverified — check manually" rather than faking it with raw IV or realized
  volatility. See `docs/DEPLOYMENT.md` "Known gaps" for how to fix that later.

## Quick start (local)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then fill in TRADIER_API_KEY
python app.py
```

Open http://localhost:5000

For deploying this so it runs on its own every weekday morning, see
`docs/DEPLOYMENT.md`.

## Repo layout

```
trading-dashboard/
├── app.py                     # Flask app: dashboard routes + scheduler wiring
├── requirements.txt
├── .env.example
├── src/
│   ├── config.py               # env vars, watchlist, thresholds — one place to tune the strategy
│   ├── market_calendar.py      # weekday/holiday + 9:45 AM ET gate
│   ├── tradier_client.py       # thin Tradier market-data API wrapper (read-only)
│   ├── models.py                # dataclasses used across the pipeline
│   ├── strategy.py             # the entry checklist (rules 1–6 from the handoff)
│   ├── sizing.py                # position sizing + exit-level math (Section 7)
│   ├── storage.py               # JSON-file persistence for account/trades/suggestions/reviews
│   ├── daily_job.py             # orchestrates: gate check → fetch → strategy → save
│   └── weekly_review.py         # weekly Claude API call: analyzes suggestions vs. executed trades
├── templates/
│   ├── base.html                # shared header/nav all pages extend
│   ├── dashboard.html           # page 1: account & sizing, today's suggestions, log a trade
│   ├── history.html             # page 2: performance history table
│   ├── watchlist.html           # page 3: add/remove/edit watchlist symbols
│   └── review.html              # page 4: weekly Claude-generated reviews + handoff prompts
├── static/style.css
├── data/                        # runtime JSON "database" — see DEPLOYMENT.md re: volumes
│   ├── account_state.json
│   ├── trade_log.json
│   ├── suggestions.json
│   └── event_blackout_dates.json   # you maintain this: FOMC/CPI/jobs dates
├── scripts/run_daily.py        # CLI entrypoint, for use with an external cron instead of APScheduler
└── docs/
    ├── strategy-handoff.md     # your original handoff doc, copied in verbatim
    └── DEPLOYMENT.md
```
