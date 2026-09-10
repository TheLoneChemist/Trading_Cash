"""
The daily pipeline: gate check -> fetch chains for the watchlist -> run the entry
checklist -> save today's suggestions -> batch-refresh current value for open
positions. This is the only place in the app that calls Tradier for fresh data, and it
always re-checks the market-open/9:45 gate itself.

ACTIVE STRATEGY (addendum, Sept 10 2026): short-duration single-leg long options.
"""
from datetime import datetime, timezone
import pytz

from . import config, storage
from .market_calendar import can_run_now
from .occ import build_occ_symbol
from .tradier_client import TradierClient, TradierError
from .strategy import find_candidate_long_options


def _dte(expiration: str) -> int:
    exp = datetime.strptime(expiration, "%Y-%m-%d").date()
    return (exp - datetime.now().date()).days


def run_daily_job(force: bool = False) -> dict:
    """
    Returns the payload saved to data/suggestions.json and shown on the dashboard.
    `force=True` skips the market/time gate — local testing only.
    """
    allowed, reason = can_run_now()
    if not allowed and not force:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gate_reason": reason, "ran": False, "candidates": [], "errors": [],
        }
        storage.save_suggestions(payload)
        return payload

    account_state = storage.get_account_state()
    account_value = account_state.get("account_value")
    if not account_value:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gate_reason": "No account value entered yet — set it on the dashboard first.",
            "ran": False, "candidates": [], "errors": [],
        }
        storage.save_suggestions(payload)
        return payload

    open_positions = storage.get_open_positions()
    blackout_dates = storage.get_blackout_dates()
    watchlist = storage.get_watchlist()

    try:
        client = TradierClient()
    except TradierError as e:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gate_reason": str(e), "ran": False, "candidates": [], "errors": [str(e)],
        }
        storage.save_suggestions(payload)
        return payload

    all_candidates = []
    errors = []

    for entry in watchlist:
        symbol, group = entry["symbol"], entry["group"]
        try:
            quote = client.get_quote(symbol)
            spot = float(quote.get("last") or quote.get("close") or 0)
            expirations = client.get_expirations(symbol)
        except TradierError as e:
            errors.append(f"{symbol}: {e}")
            continue

        target_expirations = [
            exp for exp in expirations
            if config.DTE_MIN <= _dte(exp) <= config.DTE_MAX
        ]
        if not target_expirations:
            errors.append(f"{symbol}: no expiration found in {config.DTE_MIN}-{config.DTE_MAX} DTE window today.")
            continue

        # Nearest expiration within the short-duration window (closest to the middle).
        mid_target = (config.DTE_MIN + config.DTE_MAX) / 2
        expiration = min(target_expirations, key=lambda e: abs(_dte(e) - mid_target))

        try:
            chain = client.get_option_chain(symbol, expiration)
        except TradierError as e:
            errors.append(f"{symbol} {expiration}: {e}")
            continue

        if not chain:
            errors.append(f"{symbol} {expiration}: empty chain returned.")
            continue

        candidates = find_candidate_long_options(
            chain_rows=chain, symbol=symbol, group=group, expiration=expiration,
            spot_price=spot, dte=_dte(expiration), account_balance=account_value,
            open_positions=open_positions, blackout_dates=blackout_dates,
        )
        if not candidates:
            errors.append(f"{symbol} {expiration}: nothing affordable/liquid found — likely too expensive at this account size.")
        all_candidates.extend(candidates)

    all_candidates.sort(key=lambda c: c.confidence_score, reverse=True)

    if open_positions:
        try:
            _refresh_open_position_values(client, open_positions)
        except TradierError as e:
            errors.append(f"current-value refresh: {e}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate_reason": reason, "ran": True, "account_value_used": account_value,
        "candidates": [_candidate_to_dict(c) for c in all_candidates],
        "errors": errors,
        "skip_day": len([c for c in all_candidates if c.overall_status == "CANDIDATE"]) == 0,
    }
    storage.save_suggestions(payload)
    return payload


def _refresh_open_position_values(client: TradierClient, open_positions: list[dict]) -> None:
    """
    Single-leg version: one OCC symbol per open position. Current value = the bid
    (what you'd receive selling to close right now) — the real, conservative side of
    the market, same "use the real bid/ask, not the favorable side" rule as before.
    """
    occ_by_trade_id = {}
    symbols = []
    for t in open_positions:
        occ = build_occ_symbol(t["symbol"], t["expiration"], t["option_type"], t["strike"])
        occ_by_trade_id[t["id"]] = occ
        symbols.append(occ)

    quotes = client.get_quotes(symbols)
    fetched_at = datetime.now(pytz.timezone(config.MARKET_TZ)).strftime("%b %-d, %I:%M %p %Z")

    for trade_id, occ in occ_by_trade_id.items():
        q = quotes.get(occ)
        if q and q.get("bid") is not None:
            current_value = round(q["bid"] * 100, 2)  # per-contract, matches premium_paid units
            storage.update_trade_current_value(trade_id, current_value, fetched_at)


def _candidate_to_dict(c) -> dict:
    return {
        "symbol": c.symbol,
        "group": c.group,
        "option_type": c.option_type,
        "strike": c.leg.strike,
        "delta": c.leg.delta,
        "premium_per_share": round(c.leg.ask, 4),
        "expiration": c.leg.expiration,
        "dte": c.dte,
        "spot_price": c.spot_price,
        "cost_per_contract": c.cost_per_contract,
        "cost_pct": c.cost_pct,
        "profit_target_low": c.profit_target_low,
        "profit_target_high": c.profit_target_high,
        "stop_loss_high": c.stop_loss_high,
        "stop_loss_low": c.stop_loss_low,
        "time_stop_date": c.time_stop_date,
        "confidence_score": c.confidence_score,
        "confidence_stars": c.confidence_stars,
        "overall_status": c.overall_status,
        "warnings": c.warnings,
        "checklist": [
            {
                "rule_number": item.rule_number, "name": item.name, "status": item.status,
                "detail": item.detail, "confidence_tag": item.confidence_tag,
            }
            for item in c.checklist
        ],
    }
