"""
Position sizing and exit-level math.

ACTIVE STRATEGY (addendum, Sept 10 2026): single-leg long options. Max loss is exactly
the premium paid — no width term, no credit — because you can't lose more than you
spent buying the option. This is a structural simplification versus the old spread
formula, not a judgment call: long options just don't have a spread width.

The original credit-spread math is kept below as LEGACY for reference.
"""
from datetime import datetime, timedelta

from . import config
from .models import OptionLeg


# =====================================================================================
# ACTIVE — single-leg long option sizing and exits
# =====================================================================================

def calculate_cost_per_contract(leg: OptionLeg) -> float:
    """
    What it costs to buy this option, per contract. Uses the real ask — never the bid
    — since that's what you'd actually pay to buy, mirroring the same "use the real
    side of the market, not the favorable one" rule the spread version enforced for
    credit calculations.
    """
    return round(leg.ask * 100, 2)


def calculate_cost_pct(cost_per_contract: float, account_balance: float) -> float:
    if account_balance <= 0:
        raise ValueError("account_balance must be > 0 — enter it on the dashboard first.")
    return round(cost_per_contract / account_balance, 4)


def sizing_is_valid(cost_pct: float) -> bool:
    return config.MAX_RISK_PCT_MIN <= cost_pct <= config.MAX_RISK_PCT_MAX


def calculate_long_option_exit_levels(premium_paid: float, expiration: str) -> dict:
    """
    Exit levels per the addendum's Section 6 replacement. All [SPECULATIVE] —
    conventions restored from the very first version of this project, not backtested
    for this specific short-duration structure.

    profit_target_low/high: sell-to-close prices at +50% and +100% gain on premium.
    stop_loss_high/low: sell-to-close prices at -40% and -50% loss on premium — "no
        exceptions" per the addendum, since a short-duration long option can decay to
        worthless fast.
    time_stop_date: the expiration date itself. Flatten by expiration regardless of
        P/L — there's no 21-DTE-style buffer the way there was for a spread seller,
        since these contracts only had days of life to begin with.
    """
    profit_target_low = round(premium_paid * (1 + config.PROFIT_TARGET_PCT_MIN), 4)
    profit_target_high = round(premium_paid * (1 + config.PROFIT_TARGET_PCT_MAX), 4)
    stop_loss_high = round(premium_paid * (1 - config.STOP_LOSS_PCT_MIN), 4)
    stop_loss_low = round(premium_paid * (1 - config.STOP_LOSS_PCT_MAX), 4)

    return {
        "profit_target_low": profit_target_low,
        "profit_target_high": profit_target_high,
        "stop_loss_high": stop_loss_high,
        "stop_loss_low": stop_loss_low,
        "time_stop_date": expiration,
    }


# =====================================================================================
# LEGACY — original multi-leg credit-spread sizing (pre-addendum)
# =====================================================================================
# Not used by the active code path. Kept in case a margin account is opened later and
# spreads come back into play. See docs/strategy-handoff.md.

def calculate_credit(short_leg: OptionLeg, long_leg: OptionLeg) -> float:
    """LEGACY. Credit received per share, using short leg's real bid and long leg's real ask."""
    return round(short_leg.bid - long_leg.ask, 4)


def calculate_max_risk_per_contract(strike_width: float, credit: float) -> float:
    """LEGACY."""
    return round((strike_width - credit) * 100, 2)


def calculate_max_risk_pct(max_risk_per_contract: float, account_balance: float) -> float:
    """LEGACY."""
    if account_balance <= 0:
        raise ValueError("account_balance must be > 0 — enter it on the dashboard first.")
    return round(max_risk_per_contract / account_balance, 4)


def sizing_is_mid_band(max_risk_pct: float) -> bool:
    """LEGACY."""
    return config.LEGACY_MAX_RISK_PCT_TARGET_LOW <= max_risk_pct <= config.LEGACY_MAX_RISK_PCT_TARGET_HIGH


def calculate_exit_levels(credit: float, expiration: str) -> dict:
    """LEGACY. Credit-spread exit levels — see calculate_long_option_exit_levels for the active version."""
    profit_target_debit = round(credit * (1 - config.LEGACY_PROFIT_TARGET_PCT_OF_MAX), 4)
    stop_loss_debit = round(credit * config.LEGACY_STOP_LOSS_CREDIT_MULTIPLE, 4)

    exp_date = datetime.strptime(expiration, "%Y-%m-%d")
    time_stop_date = (exp_date - timedelta(days=config.LEGACY_TIME_STOP_DTE)).strftime("%Y-%m-%d")

    return {
        "profit_target_debit": profit_target_debit,
        "stop_loss_debit": stop_loss_debit,
        "time_stop_date": time_stop_date,
    }
