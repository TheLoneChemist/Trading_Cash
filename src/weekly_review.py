"""
Weekly Claude-powered review.

Once a week, this compares the suggestions the tool generated against what you
actually logged as executed, asks Claude (via the real Anthropic API — this costs a
small amount of real money per call, see config.py) to critique the strategy's own
code, and — specifically — to explain any gap between what was suggested and what you
actually did. The output includes a ready-to-paste prompt for a *separate*, brand-new
Claude chat: attach this repo as a zip there, paste the generated prompt, and that
session can make the code changes without needing this whole conversation's history.

This module makes exactly one external call per run (the Anthropic Messages API). It
never touches Tradier and isn't gated by market hours — it's not time-sensitive market
data, just a review of what already happened.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import requests

from . import config, storage

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

REVISIONS_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "REVISIONS.md"
)

# Kept here (not read from the actual source files) so this module doesn't need
# filesystem access to describe the repo to Claude. Update this by hand if you rename
# or restructure files — it's a map for the *next* Claude session, not live-introspected.
REPO_MAP = """\
- src/config.py — every strategy threshold: DTE window, sizing %, exit-rule %s, watchlist, group choices.
- src/strategy.py — the entry checklist: check_liquidity, iv_rank_status, check_cost_sizing,
  delta_info, check_portfolio_fit, check_upcoming_events_as_catalyst, and the selection logic
  find_candidate_long_options / _best_long_candidate. (Legacy multi-leg spread logic lives
  alongside it, prefixed legacy_ — not part of the active path.)
- src/sizing.py — cost and exit-level math: calculate_cost_per_contract, calculate_cost_pct,
  calculate_long_option_exit_levels.
- src/daily_job.py — orchestrates the 9:45 AM run: fetches chains, calls strategy.py, saves
  suggestions (storage.save_suggestions + storage.append_suggestion_history), batch-refreshes
  open-position current values.
- src/storage.py — JSON-file persistence: account state, trade log, suggestion history,
  watchlist, weekly reviews.
- src/weekly_review.py — this module.
- docs/REVISIONS.md — git-tracked changelog of past strategy/code changes, kept
  current by whichever session makes a change. NOT runtime-written by this app —
  only read, for context on what's already been tried.
- app.py — Flask routes and the dashboard/history/watchlist/review pages.
- templates/*.html, static/style.css — the UI, including the order-ticket instructions that
  tell the user exactly what to click in Webull (this has been a recurring source of
  execution mistakes worth checking against the trade log for).
- docs/strategy-handoff.md and docs/handoff-addendum-*.md — the source strategy documents
  this code implements. Any recommended change should stay consistent with these, or
  explicitly flag where it's proposing to deviate.
"""

SYSTEM_PROMPT = f"""You are reviewing one week of output from a personal, single-user \
options-trading suggestion tool. You are not placing trades or giving financial advice \
— you are critiquing the tool's own code and, especially, the gap between what it \
suggested and what its user actually executed, so a future engineering session can \
close that gap.

Repo map (for your reference — you do not have the actual source in this call, only \
the structured summary given to you in the user message):
{REPO_MAP}

You will also be given the current contents of docs/REVISIONS.md, a git-tracked \
changelog of past changes to this tool. Read it before analyzing anything: do not \
recommend a change that's already been made (check dates and descriptions against what \
you're seeing in this week's data — a recent revision may explain why a rule is now \
behaving differently), and note in your analysis if this week's data suggests a past \
change is or isn't working as intended.

You will be given a JSON summary that has already been joined against the trade log — \
do not re-derive matches yourself, trust the structure you're given, and reason from \
its actual contents rather than typical/generic patterns.

Respond in exactly two parts, in this order, using these exact headings:

## Analysis
A concise, specific critique grounded only in the data given: which checklist rules \
were chronically uninformative (e.g. always MANUAL_REVIEW) this week, which symbols \
produced no candidates and why that's expected or not, and — most importantly — a \
clear account of any gap between suggested and executed trades (`trades_NOT_matched_to_any_suggestion` \
and `suggestions_not_acted_on` in the summary). Cross-check against docs/REVISIONS.md \
so you don't re-flag something already fixed. If the data doesn't support a strong \
conclusion about something, say so plainly rather than speculating.

## Handoff prompt
A single, ready-to-paste prompt in a fenced code block, addressed to a NEW Claude chat \
that will have this repo attached as a zip (it will not have this conversation's \
history). It should:
- Reference actual file and function names from the repo map so the new session can \
navigate straight to the right code.
- Describe current vs. desired behavior for each specific change you're recommending.
- Explicitly call out anything that's a judgment call for the user rather than a \
code fix (e.g. "the user keeps buying calls that aren't on the watchlist — ask them \
whether to add that symbol, don't just add it").
- Not instruct the new session to guess at anything you're not confident about from \
this week's data — flag those as open questions for the user instead.
- End with an explicit instruction to append a new dated entry to docs/REVISIONS.md \
before finishing, in the format already used in that file (## YYYY-MM-DD — title, \
**Source:**, **Changed:**, **Why:**), crediting this review by its date, so the NEXT \
weekly review and the next new-chat handoff both have accurate history to work from.
"""


def _week_bounds(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return start, end


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def read_revisions_log() -> str:
    """
    Reads docs/REVISIONS.md as-is. Returns a placeholder if it's missing (e.g. someone
    deleted it) rather than failing the whole review over a missing doc file.
    """
    try:
        with open(REVISIONS_LOG_PATH, "r") as f:
            return f.read()
    except FileNotFoundError:
        return "(docs/REVISIONS.md not found — no revision history available yet.)"


def build_weekly_summary(days: int = None) -> dict:
    """
    Pre-joins suggestion history and the trade log into a compact structured summary.
    Done here in plain Python, not left to the API call, so Claude's one call is spent
    on interpretation rather than data wrangling — and so the join logic is testable
    without hitting the network.
    """
    days = days or config.WEEKLY_REVIEW_LOOKBACK_DAYS
    start, end = _week_bounds(days)

    history = storage.get_suggestion_history()
    trades = storage.get_trade_log()

    period_runs = [h for h in history if (dt := _parse_iso(h.get("generated_at"))) and start <= dt <= end]
    period_trades = [t for t in trades if (dt := _parse_iso(t.get("logged_at"))) and start <= dt <= end]

    all_candidates = [c for h in period_runs for c in h.get("candidates", [])]
    candidates_by_symbol: dict[str, int] = {}
    rule_stats: dict[str, dict[str, int]] = {}
    confidences = []
    for c in all_candidates:
        candidates_by_symbol[c["symbol"]] = candidates_by_symbol.get(c["symbol"], 0) + 1
        confidences.append(c.get("confidence_score", 0))
        for item in c.get("checklist", []):
            rs = rule_stats.setdefault(item["name"], {})
            rs[item["status"]] = rs.get(item["status"], 0) + 1

    error_counts: dict[str, int] = {}
    for h in period_runs:
        for e in h.get("errors", []):
            error_counts[e] = error_counts.get(e, 0) + 1

    def _same_contract(c: dict, t: dict) -> bool:
        return (
            c.get("symbol") == t.get("symbol")
            and c.get("option_type") == t.get("option_type")
            and c.get("strike") == t.get("strike")
            and c.get("expiration") == t.get("expiration")
        )

    matched, unmatched = [], []
    for t in period_trades:
        hit = any(_same_contract(c, t) for h in period_runs for c in h.get("candidates", []))
        record = {
            "symbol": t.get("symbol"), "option_type": t.get("option_type"),
            "strike": t.get("strike"), "expiration": t.get("expiration"),
            "premium_paid": t.get("premium_paid"), "status": t.get("status"),
            "notes": t.get("notes"), "logged_at": t.get("logged_at"),
        }
        (matched if hit else unmatched).append(record)

    acted_on_keys = {
        (t.get("symbol"), t.get("option_type"), t.get("strike"), t.get("expiration"))
        for t in period_trades
    }
    suggestions_not_acted_on = [
        {
            "symbol": c["symbol"], "option_type": c.get("option_type"), "strike": c.get("strike"),
            "expiration": c.get("expiration"), "confidence_score": c.get("confidence_score"),
        }
        for h in period_runs for c in h.get("candidates", [])
        if c.get("overall_status") == "CANDIDATE"
        and (c["symbol"], c.get("option_type"), c.get("strike"), c.get("expiration")) not in acted_on_keys
    ]

    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "days_run": len(period_runs),
        "days_skipped": sum(1 for h in period_runs if h.get("skip_day")),
        "total_candidates_generated": len(all_candidates),
        "candidates_by_symbol": candidates_by_symbol,
        "checklist_rule_stats": rule_stats,
        "avg_confidence_score": round(sum(confidences) / len(confidences), 1) if confidences else None,
        "recurring_errors": error_counts,
        "trades_logged_this_period": len(period_trades),
        "trades_matched_to_a_suggestion": matched,
        "trades_NOT_matched_to_any_suggestion": unmatched,
        "suggestions_not_acted_on": suggestions_not_acted_on,
    }


def run_weekly_review(days: int = None) -> dict:
    """
    Builds the summary, makes the one Anthropic API call, and persists the result via
    storage.add_weekly_review. Raises on failure — the caller (the scheduled job or the
    manual /review/run route) is responsible for catching and recording the failure so
    it's visible on the Review page instead of silently vanishing.
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Get one at console.anthropic.com and add it "
            "to your .env file or Railway service variables."
        )

    days = days or config.WEEKLY_REVIEW_LOOKBACK_DAYS
    summary = build_weekly_summary(days)
    revisions_log = read_revisions_log()
    user_message = (
        "Here is docs/REVISIONS.md — the changelog of past changes to this tool. "
        "Read it before analyzing anything below, so you don't recommend something "
        "already done:\n\n" + revisions_log + "\n\n---\n\n"
        "Here is this week's structured summary from the suggestion tool. It has "
        "already been joined against the trade log — trust this structure rather than "
        "re-deriving matches yourself:\n\n" + json.dumps(summary, indent=2, default=str)
    )

    resp = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.ANTHROPIC_MODEL,
            "max_tokens": 4000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=90,
    )
    if not resp.ok:
        raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    analysis_and_prompt = "\n".join(text_blocks)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "model": config.ANTHROPIC_MODEL,
        "summary": summary,
        "analysis_and_prompt": analysis_and_prompt,
        "error": None,
    }
    storage.add_weekly_review(result)
    return result


def run_weekly_review_safe(days: int = None) -> dict:
    """
    Same as run_weekly_review, but never raises — records a failed entry (with the
    error message) instead, so a bad API key or network hiccup shows up on the Review
    page rather than silently vanishing from a scheduled run's logs.
    """
    try:
        return run_weekly_review(days)
    except Exception as e:  # noqa: BLE001 — deliberately broad: this is a background job
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period_days": days or config.WEEKLY_REVIEW_LOOKBACK_DAYS,
            "model": config.ANTHROPIC_MODEL,
            "summary": None,
            "analysis_and_prompt": None,
            "error": str(e),
        }
        storage.add_weekly_review(result)
        return result
