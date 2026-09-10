"""
Central configuration. Every threshold from the strategy lives here so you never have
to hunt through logic files to change a number.

ACTIVE STRATEGY (as of the Sept 10, 2026 addendum): short-duration single-leg long
puts/calls. Multi-leg credit spreads were ruled out for the real account — FINRA Rule
4210 sets a hard $2,000 minimum equity to open a margin account at all, and spreads
require one; single-leg long options don't. See
docs/handoff-addendum-short-duration-long-options.md for the full reasoning. The
original credit-spread constants are kept below, clearly marked LEGACY, in case a
margin account gets opened later and spreads come back into play — but the app's
active code path (strategy.py, sizing.py, daily_job.py) uses the single-leg constants.

Where a value is [CONVENTION] or [SPECULATIVE], it's noted below too — the source
docs' confidence tagging is load-bearing and this repo doesn't quietly upgrade a guess
to a fact.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Tradier -----------------------------------------------------------------
TRADIER_API_KEY = os.environ.get("TRADIER_API_KEY", "")
TRADIER_ENV = os.environ.get("TRADIER_ENV", "sandbox")  # "sandbox" or "production"
TRADIER_BASE_URL = (
    "https://sandbox.tradier.com/v1"
    if TRADIER_ENV == "sandbox"
    else "https://api.tradier.com/v1"
)

# --- Admin / scheduling --------------------------------------------------------
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
PORT = int(os.environ.get("PORT", 5000))

MARKET_TZ = "America/New_York"
EARLIEST_RUN_HOUR = 9
EARLIEST_RUN_MINUTE = 45

# --- Weekly Claude-powered review -----------------------------------------------
# Analyzes the past week's suggestions against what you actually logged, and produces
# a ready-to-paste prompt for a NEW Claude chat (with this repo attached) to make the
# resulting code changes. See src/weekly_review.py. This calls a real, billed
# Anthropic API endpoint — unlike Tradier's free sandbox, each run has a real dollar
# cost (small, but real), which is why it's weekly rather than daily and why the
# manual trigger requires the same admin secret as /refresh.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
WEEKLY_REVIEW_LOOKBACK_DAYS = 7
# Sunday evening ET, so it looks back over a full trading week before Monday's run.
WEEKLY_REVIEW_DAY_OF_WEEK = "sun"
WEEKLY_REVIEW_HOUR = 18
WEEKLY_REVIEW_MINUTE = 0

# --- Watchlist -----------------------------------------------------------------
# NOTE: this is only the DEFAULT seed for a fresh deploy. The live, editable watchlist
# lives in data/watchlist.json, managed from the Watchlist page.
#
# Addendum Section 4: SPY is likely priced out of this structure — a single-leg put
# near a reasonable delta ran over $6,000/contract, nowhere close to a small account's
# budget. Rather than hardcode SPY out, the cost-based filter in strategy.py
# (cost_pct <= MAX_RISK_PCT_MAX) naturally excludes it at low budgets on its own — so
# SPY stays on the default watchlist and will just come back with "no candidates found"
# most days, which is honest and doesn't require a special case. IWM (~$288/share) is
# the only underlying confirmed affordable at this budget; GLD/TLT/XLE are UNTESTED for
# single-leg pricing — don't assume they carry over from the spread watchlist.
WATCHLIST = [
    {"symbol": "SPY", "group": "broad_equity"},
    {"symbol": "IWM", "group": "broad_equity"},
    {"symbol": "GLD", "group": "commodity_unverified_diversifier"},
    {"symbol": "TLT", "group": "bonds_unverified_diversifier"},
    {"symbol": "XLE", "group": "energy_sector"},
]

# Shared group choices for the Watchlist and "log a trade" forms. Symbols sharing a
# group are treated as correlated by the rule-5 heuristic in strategy.py.
GROUP_CHOICES = [
    {"value": "broad_equity", "label": "Broad equity"},
    {"value": "commodity_unverified_diversifier", "label": "Commodity (diversification unverified)"},
    {"value": "bonds_unverified_diversifier", "label": "Bonds (diversification unverified)"},
    {"value": "energy_sector", "label": "Energy sector"},
]

# =====================================================================================
# ACTIVE STRATEGY — short-duration single-leg long options (addendum, Sept 10 2026)
# =====================================================================================

# DTE window for the long option itself. Addendum's worked example used 4 DTE; the
# broader goal (carried over from the very first version of this project) is "days,
# not weeks." [SPECULATIVE — no sourced outer bound; pick a window and paper-trade it]
DTE_MIN = 1
DTE_MAX = 7

# Rule 1: liquidity gate — mechanically unchanged from the spread version. [VERIFIED]
MAX_BID_ASK_SPREAD_ABS = 0.05
MAX_BID_ASK_SPREAD_PCT = 0.05  # of option price, whichever is looser

# Rule 2: IV Rank — same concept, OPPOSITE direction from the spread version. Selling
# premium wants IV Rank high; buying premium wants it LOW. Still not computed by this
# app (no historical-IV source wired up) — always flagged MANUAL_REVIEW either way.
# [VERIFIED concept — this is the other branch of the same sourced Option Alpha rule /
# CONVENTION exact threshold]
IV_RANK_THRESHOLD = 50

# Rule 3: strike/delta selection — addendum is explicit that NO sourced delta target
# exists for buying short-duration options. Delta is a RANKING factor only (among
# strikes that already pass the cost filter, prefer the highest |delta|) — never a
# pass/fail gate. Do not add a hard threshold here; that would fabricate precision the
# source material doesn't have. [explicitly UNRESOLVED per the addendum]

# Rule 4: position sizing — max loss on a long option is exactly the premium paid, no
# width term. Same 1-5% band as the spread version; addendum's calibration data shows
# this same knob also controls how strong a delta you can even reach (tighter sizing
# = weaker, more lottery-like exposure), which is worth knowing but not enforced as a
# separate rule. [VERIFIED — standard options mechanics for the loss-cap; CONVENTION
# for the 1-5% band itself, carried over unchanged from the spread version]
MAX_RISK_PCT_MIN = 0.01
MAX_RISK_PCT_MAX = 0.05

# --- Exit rules — restores the framing from the very first version of this project,
# since a long option's economics don't fit the credit-based framing used for spreads.
# All [SPECULATIVE] — conventions, not backtested.
PROFIT_TARGET_PCT_MIN = 0.50   # close (or trim) once up 50%...
PROFIT_TARGET_PCT_MAX = 1.00   # ...to as much as 100% on premium paid
STOP_LOSS_PCT_MIN = 0.40       # close once down 40%...
STOP_LOSS_PCT_MAX = 0.50       # ...to 50% of premium paid, no exceptions
# Time stop: flatten by expiration regardless of P/L. With only days of life on the
# contract to begin with, this mostly collapses into "exit by end of the week" —
# there's no 21-DTE-style gamma buffer the way there was for a spread seller.

# =====================================================================================
# LEGACY — original multi-leg credit-spread constants (pre-addendum)
# =====================================================================================
# Kept for reference / in case a margin account is opened later and spreads come back
# into play (see docs/strategy-handoff.md). NOT used by the active code path.

LEGACY_SPREAD_DTE_MIN = 30
LEGACY_SPREAD_DTE_MAX = 45
LEGACY_SPREAD_DTE_MAX_LOW_IV = 90

LEGACY_SPREAD_IV_RANK_THRESHOLD = 50  # favors SELLING — opposite of the active rule above

LEGACY_SHORT_DELTA_MIN = 0.14
LEGACY_SHORT_DELTA_MAX = 0.30

LEGACY_MAX_RISK_PCT_TARGET_LOW = 0.02
LEGACY_MAX_RISK_PCT_TARGET_HIGH = 0.03

LEGACY_PROFIT_TARGET_PCT_OF_MAX = 0.50
LEGACY_STOP_LOSS_CREDIT_MULTIPLE = 2.0
LEGACY_TIME_STOP_DTE = 21

LEGACY_DEFAULT_STRIKE_WIDTH = 1.0
