"""
Market-day and time-of-day gating.

This is the module that enforces "never call Tradier before 9:45 AM ET, and never on a
day the market's closed." Every entrypoint that talks to Tradier (daily_job.py, the
/refresh route) must call can_run_now() first and bail out if it returns False.

Holiday list is hardcoded and must be updated yearly — see NYSE_HOLIDAYS below. This
repo intentionally avoids adding a market-calendar dependency to keep things simple for
a one-person deploy; if you'd rather not maintain the list by hand, swap this module for
the `pandas_market_calendars` package later.
"""
from datetime import datetime, time
import pytz

from . import config

# NYSE full-day closures. Update this list every December for the following year.
# Source: nyse.com holiday calendar. Early-close days (e.g. day after Thanksgiving)
# are NOT treated specially here — the app will still gate at 9:45 AM and run normally;
# it just won't know the market closes early, which only matters if you extend this
# tool to also watch for end-of-day exit timing later.
NYSE_HOLIDAYS_2026 = {
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents' Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
}


def _now_et() -> datetime:
    return datetime.now(pytz.timezone(config.MARKET_TZ))


def is_market_day(dt: datetime = None) -> bool:
    """Weekday and not a hardcoded NYSE holiday. Does not check early closes."""
    dt = dt or _now_et()
    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if dt.strftime("%Y-%m-%d") in NYSE_HOLIDAYS_2026:
        return False
    return True


def is_past_gate_time(dt: datetime = None) -> bool:
    """True once it's 9:45 AM ET or later, regardless of day."""
    dt = dt or _now_et()
    gate = time(config.EARLIEST_RUN_HOUR, config.EARLIEST_RUN_MINUTE)
    return dt.time() >= gate


def can_run_now(dt: datetime = None) -> tuple[bool, str]:
    """
    The single check every Tradier-calling code path must pass.
    Returns (allowed, reason) — reason is human-readable, for logging/dashboard display.
    """
    dt = dt or _now_et()
    if not is_market_day(dt):
        return False, f"{dt.strftime('%A %Y-%m-%d')} is a weekend or holiday — market closed."
    if not is_past_gate_time(dt):
        return False, (
            f"It's {dt.strftime('%I:%M %p %Z')} — waiting until "
            f"{config.EARLIEST_RUN_HOUR}:{config.EARLIEST_RUN_MINUTE:02d} AM ET."
        )
    return True, "Market open and past the 9:45 AM ET gate."


def trading_days_until(expiration_str: str) -> int:
    """
    Number of NYSE trading days between today (ET) and an expiration date (YYYY-MM-DD),
    not counting today itself. 0 means expiration is today; a negative number means
    it's already passed. Used by the History page to flag positions expiring soon.
    """
    from datetime import date, timedelta

    today = _now_et().date()
    exp = datetime.strptime(expiration_str, "%Y-%m-%d").date()
    if exp < today:
        return (exp - today).days  # negative
    if exp == today:
        return 0
    count = 0
    d = today + timedelta(days=1)
    while d <= exp:
        probe = datetime(d.year, d.month, d.day)
        if is_market_day(probe):
            count += 1
        d += timedelta(days=1)
    return count
