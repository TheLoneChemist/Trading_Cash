"""
Flask entrypoint.

Routes:
  GET  /              the dashboard
  POST /update-account   save account value / buying power you entered
  POST /log-trade        log a trade YOU already placed manually in Webull
  POST /close-trade       mark an open logged trade as closed
  POST /refresh           admin-only: manually re-run the daily job (still gated
                           by market-day/9:45 unless ?force=1, which is for local
                           testing only — see the warning in that route)
  GET  /health            for Railway's health check

No route here ever places, modifies, or cancels a broker order. That is intentional.
"""
import atexit
import logging
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from src import config, storage, sizing
from src.daily_job import run_daily_job
from src.formatting import format_expiration_webull
from src.market_calendar import trading_days_until
from src.weekly_review import run_weekly_review_safe, read_revisions_log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

app = Flask(__name__)
app.jinja_env.filters["webull_exp"] = format_expiration_webull


def _today_str() -> str:
    return datetime.now(pytz.timezone(config.MARKET_TZ)).strftime("%A, %B %-d, %Y")


@app.route("/")
def dashboard():
    suggestions = storage.get_suggestions()
    account = storage.get_account_state()
    return render_template(
        "dashboard.html",
        active_page="dashboard",
        today_str=_today_str(),
        suggestions=suggestions,
        account=account,
        group_choices=config.GROUP_CHOICES,
    )


@app.route("/history")
def history():
    """
    Open positions are pinned above closed ones, sorted by soonest-to-expire, with the
    suggested exit levels computed when the trade was logged.

    Current value is NOT fetched here. It's batched into the 9:45 AM daily job
    (src/daily_job.py::_refresh_open_position_values) alongside the watchlist chain
    pulls, so opening this page never itself calls Tradier — you're reading whatever
    value that morning's run last stored. If you log a brand-new trade after the job
    already ran today, its current value stays blank until tomorrow's run (or a manual
    /refresh).
    """
    all_trades = storage.get_trade_log()
    open_trades = [t for t in all_trades if t.get("status") == "open"]
    closed_trades = sorted(
        (t for t in all_trades if t.get("status") != "open"),
        key=lambda t: t.get("logged_at", ""),
        reverse=True,
    )

    for t in open_trades:
        t["dte_trading"] = trading_days_until(t["expiration"])
        t["expiring_soon"] = t["dte_trading"] <= 2
    open_trades.sort(key=lambda t: t["dte_trading"])

    return render_template(
        "history.html",
        active_page="history",
        today_str=_today_str(),
        open_trades=open_trades,
        closed_trades=closed_trades,
    )


@app.route("/watchlist")
def watchlist_page():
    group_labels = {g["value"]: g["label"] for g in config.GROUP_CHOICES}
    return render_template(
        "watchlist.html",
        active_page="watchlist",
        today_str=_today_str(),
        watchlist=storage.get_watchlist(),
        group_choices=config.GROUP_CHOICES,
        group_labels=group_labels,
    )


@app.route("/watchlist/add", methods=["POST"])
def add_watchlist():
    symbol = request.form.get("symbol", "").strip()
    group = request.form.get("group", "")
    if not symbol or not group:
        return "Symbol and group are both required.", 400
    storage.add_watchlist_symbol(symbol, group)
    return redirect(url_for("watchlist_page"))


@app.route("/watchlist/remove", methods=["POST"])
def remove_watchlist():
    symbol = request.form.get("symbol", "")
    if not symbol:
        return "Symbol is required.", 400
    storage.remove_watchlist_symbol(symbol)
    return redirect(url_for("watchlist_page"))


@app.route("/watchlist/update", methods=["POST"])
def update_watchlist():
    symbol = request.form.get("symbol", "")
    group = request.form.get("group", "")
    if not symbol or not group:
        return "Symbol and group are both required.", 400
    storage.update_watchlist_symbol_group(symbol, group)
    return redirect(url_for("watchlist_page"))


@app.route("/update-account", methods=["POST"])
def update_account():
    try:
        account_value = float(request.form["account_value"])
        buying_power = float(request.form["buying_power"])
    except (KeyError, ValueError):
        return "Enter valid numbers for account value and buying power.", 400
    storage.set_account_state(account_value, buying_power)
    return redirect(url_for("dashboard"))


@app.route("/log-trade", methods=["POST"])
def log_trade():
    """
    Logs a single-leg long option trade the user placed manually (active strategy per
    the Sept 10 2026 addendum). This route writes only to the local JSON trade log —
    it never contacts Tradier's or Webull's order endpoints.
    """
    required = ["symbol", "option_type", "strike", "expiration", "premium_paid", "contracts"]
    missing = [f for f in required if not request.form.get(f)]
    if missing:
        return f"Missing fields: {', '.join(missing)}", 400

    try:
        trade = {
            "symbol": request.form["symbol"].upper().strip(),
            "group": request.form.get("group", ""),
            "option_type": request.form["option_type"],
            "strike": float(request.form["strike"]),
            "expiration": request.form["expiration"],
            # premium_paid is the PER-CONTRACT total dollar cost — matches Webull's own
            # "Total Cost" column exactly, on purpose. Not a $/share price. Storing it
            # in whatever unit the user has to translate invites the same kind of
            # misread that caused the earlier single-leg-vs-spread confusion.
            "premium_paid": float(request.form["premium_paid"]),
            "contracts": int(request.form["contracts"]),
            "direction": "bullish" if request.form["option_type"] == "call" else "bearish",
            "notes": request.form.get("notes", ""),
        }
    except ValueError:
        return "Strike, premium, and contracts must be numbers.", 400

    # Compute and store exit levels at log time (addendum Section 6 — see sizing.py
    # for the caveats on how "unverified" these conventions are).
    try:
        exits = sizing.calculate_long_option_exit_levels(trade["premium_paid"], trade["expiration"])
        trade.update(exits)
    except ValueError:
        pass  # bad expiration format — leave exit levels unset rather than fail the log

    storage.add_trade(trade)
    return redirect(url_for("dashboard"))


@app.route("/close-trade", methods=["POST"])
def close_trade():
    try:
        trade_id = int(request.form["trade_id"])
    except (KeyError, ValueError):
        return "Invalid trade id.", 400
    status = request.form.get("status", "closed_profit")
    closed_price = request.form.get("closed_price")
    closed_price = float(closed_price) if closed_price else None
    ok = storage.update_trade_status(trade_id, status, closed_price)
    if not ok:
        return "Trade not found.", 404
    return redirect(url_for("dashboard"))


@app.route("/refresh", methods=["POST"])
def refresh():
    """
    Manually re-runs the daily job. Requires the X-Admin-Secret header to match
    ADMIN_SECRET so this can't be hit by a random visitor and burn your Tradier rate
    limit. `force=1` bypasses the market/time gate — only use that for local testing;
    leaving it off means this route behaves exactly like the scheduled job.
    """
    if not config.ADMIN_SECRET or request.headers.get("X-Admin-Secret") != config.ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    force = request.args.get("force") == "1"
    payload = run_daily_job(force=force)
    return jsonify(payload)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


def _split_review_text(text: str) -> tuple[str, str]:
    """Splits the model's response into (analysis, handoff_prompt) on the '## Handoff prompt' heading."""
    if not text:
        return "", ""
    marker = "## Handoff prompt"
    idx = text.find(marker)
    if idx == -1:
        return text.replace("## Analysis", "").strip(), ""
    analysis = text[:idx].replace("## Analysis", "").strip()
    handoff = text[idx + len(marker):].strip()
    # Strip a leading fenced-code-block wrapper if the model included one, so the
    # textarea holds just the prompt text, not literal ``` fences.
    if handoff.startswith("```"):
        handoff = handoff.split("\n", 1)[1] if "\n" in handoff else ""
        if handoff.endswith("```"):
            handoff = handoff[:-3]
    return analysis, handoff.strip()


@app.route("/review")
def review_page():
    reviews = list(reversed(storage.get_weekly_reviews()))
    parsed = []
    for r in reviews:
        analysis, handoff = _split_review_text(r.get("analysis_and_prompt") or "")
        parsed.append({**r, "analysis": analysis, "handoff_prompt": handoff})
    return render_template(
        "review.html",
        active_page="review",
        today_str=_today_str(),
        reviews=parsed,
        has_api_key=bool(config.ANTHROPIC_API_KEY),
        revisions_log=read_revisions_log(),
    )


@app.route("/review/run", methods=["POST"])
def review_run():
    """
    Manually triggers the weekly review. Requires X-Admin-Secret, same as /refresh —
    arguably more important to protect here, since unlike Tradier's free sandbox, each
    call to this route costs real money against your Anthropic API key.
    """
    if not config.ADMIN_SECRET or request.headers.get("X-Admin-Secret") != config.ADMIN_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    result = run_weekly_review_safe()
    return jsonify(result)


# --- Scheduler ---------------------------------------------------------------------
# Fires every weekday morning; run_daily_job() re-validates the market-day/9:45 gate
# itself, so a slightly-early or misfired trigger is harmless — it'll just no-op and
# record the reason in suggestions.json for the dashboard to show.
def start_scheduler():
    scheduler = BackgroundScheduler(timezone=pytz.timezone(config.MARKET_TZ))
    scheduler.add_job(
        run_daily_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=45),
        id="daily_suggestion_job",
        replace_existing=True,
    )
    scheduler.add_job(
        run_weekly_review_safe,
        trigger=CronTrigger(
            day_of_week=config.WEEKLY_REVIEW_DAY_OF_WEEK,
            hour=config.WEEKLY_REVIEW_HOUR,
            minute=config.WEEKLY_REVIEW_MINUTE,
        ),
        id="weekly_review_job",
        replace_existing=True,
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    logger.info("Scheduler started: daily job 9:45 AM ET Mon-Fri; weekly review Sun 6 PM ET.")
    return scheduler


if __name__ == "__main__":
    start_scheduler()
    app.run(host="0.0.0.0", port=config.PORT)
else:
    # When run under gunicorn (production), still start the scheduler once.
    start_scheduler()
