"""
Simple JSON-file "database." No SQL, no ORM — deliberately, so a non-professional
developer can open any data/*.json file in a text editor and understand or fix it by
hand. Fine for one person's trade log; if you outgrow it, swap for SQLite without
changing the rest of the app (only these functions would need to change).

IMPORTANT (Railway): the container filesystem is ephemeral by default. Without a
Railway Volume mounted at the data/ path, every deploy wipes these files. See
docs/DEPLOYMENT.md.
"""
import json
import os
import threading
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_lock = threading.Lock()


def _path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


def _read(filename: str, default):
    path = _path(filename)
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        content = f.read().strip()
        if not content:
            return default
        return json.loads(content)


def _write(filename: str, data) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = _path(filename)
    with _lock:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, path)  # atomic on POSIX


# --- Account state ---------------------------------------------------------------
def get_account_state() -> dict:
    return _read("account_state.json", {"account_value": None, "buying_power": None, "updated_at": None})


def set_account_state(account_value: float, buying_power: float) -> dict:
    state = {
        "account_value": account_value,
        "buying_power": buying_power,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write("account_state.json", state)
    return state


# --- Trade log ---------------------------------------------------------------------
# Trades support PARTIAL closes (scaling out): `contracts` is always the ORIGINAL
# total bought, and `closes` is a list of individual sell-to-close events, each
# {"id", "contracts", "price_per_contract", "closed_at"}. "status" and
# "contracts_remaining" are derived, not authoritative — _recompute_status() is the
# single place that keeps them in sync, called after every add/edit/delete.
def get_trade_log() -> list[dict]:
    return _read("trade_log.json", [])


def _contracts_closed(trade: dict) -> int:
    return sum(c.get("contracts", 0) for c in trade.get("closes", []))


def _recompute_status(trade: dict) -> None:
    remaining = trade.get("contracts", 0) - _contracts_closed(trade)
    trade["contracts_remaining"] = remaining
    trade["status"] = "open" if remaining > 0 else "closed"
    closes = trade.get("closes", [])
    trade["closed_at"] = closes[-1]["closed_at"] if remaining <= 0 and closes else None


def add_trade(trade: dict) -> dict:
    trades = get_trade_log()
    trade["id"] = (max((t.get("id", 0) for t in trades), default=0)) + 1
    trade["logged_at"] = datetime.now(timezone.utc).isoformat()
    trade.setdefault("closes", [])
    _recompute_status(trade)
    trades.append(trade)
    _write("trade_log.json", trades)
    return trade


def add_close(trade_id: int, contracts: int, price_per_contract: float) -> tuple[bool, str]:
    """
    Records a partial (or full) sell-to-close. Returns (ok, error_message) — error
    covers trying to close more contracts than actually remain open, which the
    caller should show back to the user rather than silently clamping (clamping a
    typo'd quantity could hide a mistake instead of catching it).
    """
    trades = get_trade_log()
    for t in trades:
        if t.get("id") == trade_id:
            remaining = t.get("contracts", 0) - _contracts_closed(t)
            if contracts <= 0:
                return False, "Contracts to close must be at least 1."
            if contracts > remaining:
                return False, f"Only {remaining} contract(s) remain open on this trade."
            closes = t.setdefault("closes", [])
            close_id = (max((c.get("id", 0) for c in closes), default=0)) + 1
            closes.append({
                "id": close_id,
                "contracts": contracts,
                "price_per_contract": price_per_contract,
                "closed_at": datetime.now(timezone.utc).isoformat(),
            })
            _recompute_status(t)
            _write("trade_log.json", trades)
            return True, ""
    return False, "Trade not found."


def edit_close(trade_id: int, close_id: int, contracts: int, price_per_contract: float) -> tuple[bool, str]:
    """Corrects a previously-logged close (wrong price or quantity entered)."""
    trades = get_trade_log()
    for t in trades:
        if t.get("id") == trade_id:
            closes = t.get("closes", [])
            target = next((c for c in closes if c.get("id") == close_id), None)
            if target is None:
                return False, "Close entry not found."
            other_closed = sum(c.get("contracts", 0) for c in closes if c.get("id") != close_id)
            if contracts <= 0:
                return False, "Contracts to close must be at least 1."
            if other_closed + contracts > t.get("contracts", 0):
                return False, f"That would close more than the {t.get('contracts')} contracts originally bought."
            target["contracts"] = contracts
            target["price_per_contract"] = price_per_contract
            _recompute_status(t)
            _write("trade_log.json", trades)
            return True, ""
    return False, "Trade not found."


def delete_close(trade_id: int, close_id: int) -> bool:
    trades = get_trade_log()
    for t in trades:
        if t.get("id") == trade_id:
            closes = t.get("closes", [])
            new_closes = [c for c in closes if c.get("id") != close_id]
            if len(new_closes) == len(closes):
                return False  # nothing removed
            t["closes"] = new_closes
            _recompute_status(t)
            _write("trade_log.json", trades)
            return True
    return False


def update_trade_fields(trade_id: int, updates: dict) -> tuple[bool, str]:
    """
    General editor for a trade's core fields (symbol, option_type, strike,
    expiration, group, contracts, premium_paid, notes) — covers "I saved the wrong
    info" for anything that isn't a close event itself. Rejects lowering `contracts`
    below what's already been recorded as closed, rather than silently producing a
    negative contracts_remaining.
    """
    allowed = {"symbol", "option_type", "strike", "expiration", "group", "contracts", "premium_paid", "notes"}
    trades = get_trade_log()
    for t in trades:
        if t.get("id") == trade_id:
            if "contracts" in updates:
                new_total = updates["contracts"]
                if new_total < _contracts_closed(t):
                    return False, f"Can't set contracts below the {_contracts_closed(t)} already recorded as closed."
            for k, v in updates.items():
                if k in allowed:
                    t[k] = v
            _recompute_status(t)
            _write("trade_log.json", trades)
            return True, ""
    return False, "Trade not found."


def update_trade_current_value(trade_id: int, current_value: float, fetched_at: str) -> bool:
    """Called once a day by the daily job's batched refresh, not by any page load."""
    trades = get_trade_log()
    for t in trades:
        if t.get("id") == trade_id:
            t["current_value"] = current_value
            t["current_value_fetched_at"] = fetched_at
            _write("trade_log.json", trades)
            return True
    return False


def get_open_positions() -> list[dict]:
    return [t for t in get_trade_log() if t.get("status") == "open"]


# --- Daily suggestions --------------------------------------------------------------
def get_suggestions() -> dict:
    return _read("suggestions.json", {"generated_at": None, "gate_reason": None, "candidates": []})


def save_suggestions(payload: dict) -> None:
    _write("suggestions.json", payload)


# --- Event blackout dates (user-maintained) ------------------------------------------
def get_blackout_dates() -> list[dict]:
    return _read("event_blackout_dates.json", [])


# --- Watchlist (user-editable via the Watchlist page) ---------------------------------
def get_watchlist() -> list[dict]:
    """
    Returns the live, user-editable watchlist. Seeded from config.WATCHLIST the first
    time this is called if data/watchlist.json doesn't exist yet, so a fresh clone of
    the repo starts with the same five symbols from the strategy handoff.
    """
    from . import config  # local import avoids a circular import at module load time

    default = [dict(entry) for entry in config.WATCHLIST]
    watchlist = _read("watchlist.json", None)
    if watchlist is None:
        _write("watchlist.json", default)
        return default
    return watchlist


def add_watchlist_symbol(symbol: str, group: str) -> list[dict]:
    watchlist = get_watchlist()
    symbol = symbol.upper().strip()
    if any(w["symbol"] == symbol for w in watchlist):
        return watchlist  # already present — no duplicates
    watchlist.append({"symbol": symbol, "group": group})
    _write("watchlist.json", watchlist)
    return watchlist


def remove_watchlist_symbol(symbol: str) -> list[dict]:
    watchlist = [w for w in get_watchlist() if w["symbol"] != symbol.upper().strip()]
    _write("watchlist.json", watchlist)
    return watchlist


def update_watchlist_symbol_group(symbol: str, new_group: str) -> list[dict]:
    symbol = symbol.upper().strip()
    watchlist = get_watchlist()
    for w in watchlist:
        if w["symbol"] == symbol:
            w["group"] = new_group
    _write("watchlist.json", watchlist)
    return watchlist


# --- Suggestion history (for the weekly review) ----------------------------------
# save_suggestions() above only ever holds the LATEST day's run, for the dashboard.
# This keeps a rolling log of every run so the weekly review has something to look
# back over. Capped to avoid the file growing forever on a personal deploy.
SUGGESTION_HISTORY_MAX_ENTRIES = 60  # ~2 months of daily runs


def append_suggestion_history(payload: dict) -> None:
    history = _read("suggestion_history.json", [])
    history.append(payload)
    if len(history) > SUGGESTION_HISTORY_MAX_ENTRIES:
        history = history[-SUGGESTION_HISTORY_MAX_ENTRIES:]
    _write("suggestion_history.json", history)


def get_suggestion_history() -> list[dict]:
    return _read("suggestion_history.json", [])


# --- Weekly Claude-powered reviews -------------------------------------------------
WEEKLY_REVIEW_MAX_ENTRIES = 26  # ~6 months of weekly runs


def add_weekly_review(review: dict) -> dict:
    reviews = _read("weekly_reviews.json", [])
    review["id"] = (max((r.get("id", 0) for r in reviews), default=0)) + 1
    reviews.append(review)
    if len(reviews) > WEEKLY_REVIEW_MAX_ENTRIES:
        reviews = reviews[-WEEKLY_REVIEW_MAX_ENTRIES:]
    _write("weekly_reviews.json", reviews)
    return review


def get_weekly_reviews() -> list[dict]:
    return _read("weekly_reviews.json", [])
