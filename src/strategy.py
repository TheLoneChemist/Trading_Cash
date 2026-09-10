"""
Entry checklist logic.

ACTIVE STRATEGY (addendum, Sept 10 2026): short-duration single-leg long options.
Legacy multi-leg credit-spread logic is kept at the bottom of this file, clearly
marked, in case a margin account is opened later and spreads come back into play.
"""
from datetime import datetime

from . import config
from .models import OptionLeg, ChecklistItem, LongOptionCandidate, SpreadCandidate
from . import sizing


# =====================================================================================
# Shared across active and legacy paths
# =====================================================================================

def check_liquidity(leg: OptionLeg) -> tuple[bool, str]:
    """Rule 1: liquidity gate. Mechanically unchanged by the addendum. [VERIFIED]"""
    threshold = max(config.MAX_BID_ASK_SPREAD_ABS, config.MAX_BID_ASK_SPREAD_PCT * leg.mid)
    ok = leg.spread_abs <= threshold and leg.bid > 0
    detail = f"bid/ask spread ${leg.spread_abs:.2f} vs threshold ${threshold:.2f}"
    return ok, detail


def check_portfolio_fit(candidate_group: str, candidate_direction: str, open_positions: list[dict]) -> tuple[str, str]:
    """
    Rule 5: portfolio fit / correlation check — same same-group, same-direction
    heuristic used for spreads. "Direction" here is bullish (long call) or bearish
    (long put), same labels as before.
    """
    equity_like = {"broad_equity"}
    same_group_same_direction = [
        p for p in open_positions
        if p.get("group") == candidate_group
        and p.get("direction") == candidate_direction
        and candidate_group in equity_like
    ]
    if same_group_same_direction:
        tickers = ", ".join(p["symbol"] for p in same_group_same_direction)
        return (
            "MANUAL_REVIEW",
            f"Already holding {candidate_direction} exposure in the same group via "
            f"{tickers} — no live correlation data confirms these move independently. "
            f"Review before stacking another {candidate_direction} position.",
        )
    return "PASS", "No same-group, same-direction open positions found (heuristic check only)."


def score_confidence(checklist: list[ChecklistItem]) -> tuple[float, int]:
    """
    0-100 score and 0-5 stars, over only the PASS/FAIL/MANUAL_REVIEW items — INFO items
    (delta ranking, event-as-catalyst framing) are informational and excluded from the
    denominator so they neither inflate nor dilute the score. MANUAL_REVIEW never
    counts as a pass, so a candidate resting entirely on unverified rules can't look
    highly confident.
    """
    scored = [c for c in checklist if c.status in ("PASS", "FAIL", "MANUAL_REVIEW")]
    if not scored:
        return 0.0, 0
    passes = sum(1 for c in scored if c.status == "PASS")
    score = round(100 * passes / len(scored), 1)
    stars = round(score / 20)
    return score, stars


def _leg_from_chain_row(row: dict, symbol: str) -> OptionLeg:
    greeks = row.get("greeks") or {}
    return OptionLeg(
        symbol=symbol,
        option_symbol=row.get("symbol", ""),
        strike=float(row.get("strike", 0)),
        expiration=row.get("expiration_date", ""),
        option_type=row.get("option_type", ""),
        bid=float(row.get("bid") or 0),
        ask=float(row.get("ask") or 0),
        delta=greeks.get("delta"),
        open_interest=row.get("open_interest"),
        volume=row.get("volume"),
    )


# =====================================================================================
# ACTIVE — single-leg long option checklist (addendum, Sept 10 2026)
# =====================================================================================

def iv_rank_status() -> ChecklistItem:
    """
    Rule 2, active version: buying premium wants IV Rank LOW (opposite of the spread
    version, which wanted it high) — same already-sourced Option Alpha rule, just the
    other branch. Still not computed by this app (no historical-IV source wired up),
    so this is always MANUAL_REVIEW, same as before — just with flipped guidance text.
    """
    return ChecklistItem(
        rule_number=2,
        name="IV Rank filter",
        status="MANUAL_REVIEW",
        detail=(
            f"IV Rank not computed by this app (no historical-IV source wired up). "
            f"For buying premium, you WANT IV Rank low — check ≤ ~{config.IV_RANK_THRESHOLD} "
            f"yourself on your broker platform before trusting this candidate. (Note: this is "
            f"the opposite direction from the old credit-spread rule.)"
        ),
        confidence_tag="CONVENTION",
    )


def check_cost_sizing(cost_pct: float) -> tuple[bool, str]:
    """
    Rule 4, active version: max loss on a long option is exactly the premium paid.
    Same 1-5% band as the spread version. [VERIFIED mechanics / CONVENTION band]
    """
    ok = sizing.sizing_is_valid(cost_pct)
    detail = (
        f"cost {cost_pct*100:.2f}% of account vs allowed "
        f"{config.MAX_RISK_PCT_MIN*100:.0f}-{config.MAX_RISK_PCT_MAX*100:.0f}%"
    )
    return ok, detail


def delta_info(leg: OptionLeg) -> ChecklistItem:
    """
    Rule 3, active version: the addendum is explicit that NO sourced delta target
    exists for buying short-duration options — delta is a ranking factor among
    already-affordable strikes, never a pass/fail gate. This is deliberately always
    INFO, never PASS/FAIL, so the confidence score doesn't fabricate precision that
    doesn't exist. It also flags the sizing/delta trade-off the addendum calls out:
    tighter sizing reaches only weaker deltas.
    """
    d = abs(leg.delta) if leg.delta is not None else None
    detail = (
        f"delta {d:.3f} — ranking factor only, no sourced threshold. Tighter position "
        f"sizing reaches weaker (more lottery-like) deltas; this was the highest-|delta| "
        f"strike that still passed the cost filter."
        if d is not None else
        "no delta returned by Tradier for this contract — cannot rank."
    )
    return ChecklistItem(
        rule_number=3,
        name="Strike selection by delta",
        status="INFO",
        detail=detail,
        confidence_tag="explicitly UNRESOLVED — flagged rather than guessed",
    )


def check_upcoming_events_as_catalyst(expiration: str, blackout_dates: list[dict]) -> tuple[str, str]:
    """
    Rule 6, active version: for a short-duration directional buyer, a scheduled
    catalyst inside the hold window can be the reason you're entering, not just a risk
    to flag before selling into it. Reframed to INFO rather than MANUAL_REVIEW when a
    hit is found — same underlying data (data/event_blackout_dates.json), different
    interpretation. [SPECULATIVE — single practitioner source, not independently
    backtested]
    """
    today = datetime.now().date()
    exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
    hits = []
    for ev in blackout_dates:
        try:
            ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if today <= ev_date <= exp_date:
            hits.append(f"{ev.get('label', 'event')} on {ev['date']}")
    if hits:
        return "INFO", (
            "Falls inside hold window: " + "; ".join(hits) +
            " — for a short-duration directional buy, this may be the entry thesis "
            "itself rather than just a risk. Confirm that's actually why you're "
            "entering, not an accident of timing."
        )
    return "PASS", "No events listed in data/event_blackout_dates.json fall inside the hold window."


def find_candidate_long_options(
    chain_rows: list[dict],
    symbol: str,
    group: str,
    expiration: str,
    spot_price: float,
    dte: int,
    account_balance: float,
    open_positions: list[dict],
    blackout_dates: list[dict],
) -> list[LongOptionCandidate]:
    """
    Scans one expiration's chain for the best affordable long put and the best
    affordable long call (at most one of each — the addendum's algorithm selects THE
    single highest-|delta| strike among those that pass the cost/liquidity filter, it
    doesn't rank a list). No directional signal exists in this strategy (the original
    RSI/VWAP/volume indicators were rejected early on and are NOT revived here) — both
    directions are surfaced so you apply your own market view.
    """
    legs = [_leg_from_chain_row(r, symbol) for r in chain_rows]
    puts = [l for l in legs if l.option_type == "put" and l.strike > 0]
    calls = [l for l in legs if l.option_type == "call" and l.strike > 0]

    candidates = []
    put_candidate = _best_long_candidate(puts, "put", symbol, group, expiration, spot_price, dte,
                                          account_balance, open_positions, blackout_dates)
    if put_candidate:
        candidates.append(put_candidate)
    call_candidate = _best_long_candidate(calls, "call", symbol, group, expiration, spot_price, dte,
                                           account_balance, open_positions, blackout_dates)
    if call_candidate:
        candidates.append(call_candidate)

    candidates.sort(key=lambda c: c.confidence_score, reverse=True)
    return candidates


def _best_long_candidate(
    legs: list[OptionLeg],
    option_type: str,
    symbol: str,
    group: str,
    expiration: str,
    spot_price: float,
    dte: int,
    account_balance: float,
    open_positions: list[dict],
    blackout_dates: list[dict],
) -> LongOptionCandidate | None:
    direction_label = "bullish" if option_type == "call" else "bearish"

    # Cost/liquidity-affordable pool per the addendum's Section 7 pseudocode.
    affordable = []
    for leg in legs:
        if leg.ask <= 0 or leg.delta is None:
            continue
        cost = sizing.calculate_cost_per_contract(leg)
        try:
            cost_pct = sizing.calculate_cost_pct(cost, account_balance)
        except ValueError:
            continue
        if cost_pct > config.MAX_RISK_PCT_MAX:
            continue
        liq_ok, _ = check_liquidity(leg)
        if not liq_ok:
            continue
        affordable.append((leg, cost, cost_pct))

    if not affordable:
        return None  # SKIP — nothing affordable and liquid this expiration

    # "select the candidate with the highest abs(delta) — no sourced floor, rank don't gate"
    leg, cost, cost_pct = max(affordable, key=lambda tup: abs(tup[0].delta))

    candidate = LongOptionCandidate(
        symbol=symbol, group=group, option_type=option_type, leg=leg,
        dte=dte, spot_price=spot_price, cost_per_contract=cost, cost_pct=cost_pct,
    )

    exits = sizing.calculate_long_option_exit_levels(cost, expiration)
    candidate.profit_target_low = exits["profit_target_low"]
    candidate.profit_target_high = exits["profit_target_high"]
    candidate.stop_loss_high = exits["stop_loss_high"]
    candidate.stop_loss_low = exits["stop_loss_low"]
    candidate.time_stop_date = exits["time_stop_date"]

    checklist = []
    liq_ok, liq_detail = check_liquidity(leg)
    checklist.append(ChecklistItem(1, "Liquidity gate", "PASS" if liq_ok else "FAIL", liq_detail, "VERIFIED"))
    checklist.append(iv_rank_status())
    checklist.append(delta_info(leg))
    size_ok, size_detail = check_cost_sizing(cost_pct)
    checklist.append(ChecklistItem(4, "Position sizing (cost = max loss)", "PASS" if size_ok else "FAIL", size_detail, "VERIFIED mechanics / CONVENTION band"))
    fit_status, fit_detail = check_portfolio_fit(group, direction_label, open_positions)
    checklist.append(ChecklistItem(5, "Portfolio fit / correlation check", fit_status, fit_detail, "VERIFIED concept / heuristic"))
    events_status, events_detail = check_upcoming_events_as_catalyst(expiration, blackout_dates)
    checklist.append(ChecklistItem(6, "Upcoming events check", events_status, events_detail, "SPECULATIVE — single-practitioner source"))

    candidate.checklist = checklist
    candidate.confidence_score, candidate.confidence_stars = score_confidence(checklist)

    hard_fail = any(c.status == "FAIL" for c in checklist)
    candidate.overall_status = "SKIP" if hard_fail else "CANDIDATE"
    if any(c.status == "MANUAL_REVIEW" for c in checklist):
        candidate.warnings.append("One or more rules need manual review before you trust this candidate.")

    return candidate


# =====================================================================================
# LEGACY — original multi-leg credit-spread checklist (pre-addendum)
# =====================================================================================
# Not used by the active code path. Kept in case a margin account is opened later.

def legacy_iv_rank_status() -> ChecklistItem:
    return ChecklistItem(
        rule_number=2, name="IV Rank filter", status="MANUAL_REVIEW",
        detail=(
            f"IV Rank not computed by this app. For SELLING credit spreads, check IV "
            f"Rank >= ~{config.LEGACY_SPREAD_IV_RANK_THRESHOLD} yourself."
        ),
        confidence_tag="CONVENTION",
    )


def legacy_check_delta(leg: OptionLeg) -> tuple[bool, str]:
    if leg.delta is None:
        return False, "no delta returned by Tradier for this contract"
    d = abs(leg.delta)
    ok = config.LEGACY_SHORT_DELTA_MIN <= d <= config.LEGACY_SHORT_DELTA_MAX
    detail = f"short leg delta {d:.3f} vs target {config.LEGACY_SHORT_DELTA_MIN}-{config.LEGACY_SHORT_DELTA_MAX}"
    return ok, detail


def legacy_check_sizing(max_risk_pct: float) -> tuple[bool, str]:
    ok = sizing.sizing_is_valid(max_risk_pct)
    band = "mid-band (comfortable)" if sizing.sizing_is_mid_band(max_risk_pct) else "edge of range"
    detail = (
        f"max risk {max_risk_pct*100:.2f}% of account vs allowed "
        f"{config.MAX_RISK_PCT_MIN*100:.0f}-{config.MAX_RISK_PCT_MAX*100:.0f}% ({band})"
    )
    return ok, detail


def legacy_check_upcoming_events(expiration: str, blackout_dates: list[dict]) -> tuple[str, str]:
    today = datetime.now().date()
    exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
    hits = []
    for ev in blackout_dates:
        try:
            ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if today <= ev_date <= exp_date:
            hits.append(f"{ev.get('label', 'event')} on {ev['date']}")
    if hits:
        return "MANUAL_REVIEW", "Falls inside hold window: " + "; ".join(hits)
    return "PASS", "No events listed fall inside the hold window."


def legacy_find_candidate_spreads(
    chain_rows: list[dict], symbol: str, group: str, expiration: str, spot_price: float,
    dte: int, account_balance: float, open_positions: list[dict], blackout_dates: list[dict],
    max_per_type: int = 2,
) -> list[SpreadCandidate]:
    """LEGACY. See docs/strategy-handoff.md for the original spread strategy this implements."""
    legs = [_leg_from_chain_row(r, symbol) for r in chain_rows]
    puts = sorted((l for l in legs if l.option_type == "put" and l.strike > 0), key=lambda l: l.strike)
    calls = sorted((l for l in legs if l.option_type == "call" and l.strike > 0), key=lambda l: l.strike)

    candidates: list[SpreadCandidate] = []
    candidates += _legacy_scan_side(puts, "put_credit", symbol, group, expiration, spot_price, dte,
                                     account_balance, open_positions, blackout_dates, max_per_type)
    candidates += _legacy_scan_side(calls, "call_credit", symbol, group, expiration, spot_price, dte,
                                     account_balance, open_positions, blackout_dates, max_per_type)

    candidates.sort(key=lambda c: c.confidence_score, reverse=True)
    return candidates


def _legacy_scan_side(
    legs, spread_type, symbol, group, expiration, spot_price, dte,
    account_balance, open_positions, blackout_dates, max_per_type,
) -> list[SpreadCandidate]:
    by_strike = {l.strike: l for l in legs}
    strikes_sorted = sorted(by_strike.keys())
    found: list[SpreadCandidate] = []

    for short_leg in legs:
        if short_leg.delta is None:
            continue
        d = abs(short_leg.delta)
        if not (config.LEGACY_SHORT_DELTA_MIN <= d <= config.LEGACY_SHORT_DELTA_MAX):
            continue

        direction = -1 if spread_type == "put_credit" else 1
        target_long_strike = short_leg.strike + direction * config.LEGACY_DEFAULT_STRIKE_WIDTH
        long_leg = by_strike.get(target_long_strike)
        if long_leg is None:
            further = [s for s in strikes_sorted if (s < short_leg.strike if direction == -1 else s > short_leg.strike)]
            further.sort(key=lambda s: abs(s - short_leg.strike))
            long_leg = by_strike[further[0]] if further else None
        if long_leg is None:
            continue

        strike_width = round(abs(short_leg.strike - long_leg.strike), 4)
        if strike_width <= 0:
            continue

        direction_label = "bullish" if spread_type == "put_credit" else "bearish"

        candidate = SpreadCandidate(
            symbol=symbol, group=group, spread_type=spread_type,
            short_leg=short_leg, long_leg=long_leg, dte=dte,
            spot_price=spot_price, strike_width=strike_width,
        )

        candidate.credit = sizing.calculate_credit(short_leg, long_leg)
        if candidate.credit <= 0:
            candidate.overall_status = "SKIP"
            candidate.warnings.append("Credit received is zero or negative at real bid/ask — skipped.")
            continue

        candidate.max_risk_per_contract = sizing.calculate_max_risk_per_contract(strike_width, candidate.credit)
        try:
            candidate.max_risk_pct = sizing.calculate_max_risk_pct(candidate.max_risk_per_contract, account_balance)
        except ValueError as e:
            candidate.overall_status = "SKIP"
            candidate.warnings.append(str(e))
            continue

        exits = sizing.calculate_exit_levels(candidate.credit, expiration)
        candidate.profit_target_debit = exits["profit_target_debit"]
        candidate.stop_loss_debit = exits["stop_loss_debit"]
        candidate.time_stop_date = exits["time_stop_date"]

        checklist = []
        liq_ok, liq_detail = check_liquidity(short_leg)
        checklist.append(ChecklistItem(1, "Liquidity gate", "PASS" if liq_ok else "FAIL", liq_detail, "VERIFIED"))
        checklist.append(legacy_iv_rank_status())
        delta_ok, delta_detail = legacy_check_delta(short_leg)
        checklist.append(ChecklistItem(3, "Strike selection by delta", "PASS" if delta_ok else "FAIL", delta_detail, "VERIFIED"))
        size_ok, size_detail = legacy_check_sizing(candidate.max_risk_pct)
        checklist.append(ChecklistItem(4, "Position sizing / fit check", "PASS" if size_ok else "FAIL", size_detail, "VERIFIED"))
        fit_status, fit_detail = check_portfolio_fit(group, direction_label, open_positions)
        checklist.append(ChecklistItem(5, "Portfolio fit / correlation check", fit_status, fit_detail, "VERIFIED concept / heuristic"))
        events_status, events_detail = legacy_check_upcoming_events(expiration, blackout_dates)
        checklist.append(ChecklistItem(6, "Upcoming events check", events_status, events_detail, "VERIFIED"))

        candidate.checklist = checklist
        candidate.confidence_score, candidate.confidence_stars = score_confidence(checklist)

        hard_fail = any(c.status == "FAIL" for c in checklist)
        candidate.overall_status = "SKIP" if hard_fail else "CANDIDATE"
        if any(c.status == "MANUAL_REVIEW" for c in checklist):
            candidate.warnings.append("One or more rules need manual review before you trust this candidate.")

        found.append(candidate)

    found.sort(key=lambda c: c.confidence_score, reverse=True)
    return found[:max_per_type]
