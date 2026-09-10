"""Shared dataclasses for the strategy pipeline."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OptionLeg:
    symbol: str          # underlying, e.g. "SPY"
    option_symbol: str   # OCC symbol from Tradier
    strike: float
    expiration: str      # YYYY-MM-DD
    option_type: str     # "put" or "call"
    bid: float
    ask: float
    delta: Optional[float]
    open_interest: Optional[int] = None
    volume: Optional[int] = None

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2, 4)

    @property
    def spread_abs(self) -> float:
        return round(self.ask - self.bid, 4)


@dataclass
class ChecklistItem:
    rule_number: int
    name: str
    status: str          # "PASS", "FAIL", "MANUAL_REVIEW", or "INFO"
    # INFO = informational only, not a pass/fail gate (e.g. delta ranking, or an
    # event that's a potential entry thesis rather than a risk to flag). INFO items
    # are shown on the card but excluded from the confidence score's denominator —
    # see strategy.py::score_confidence.
    detail: str
    confidence_tag: str  # "VERIFIED", "CONVENTION", "SPECULATIVE"


@dataclass
class LongOptionCandidate:
    """
    Active strategy candidate (addendum, Sept 10 2026): a single long put or call,
    short duration. Replaces SpreadCandidate as the primary model the app generates.
    """
    symbol: str
    group: str
    option_type: str          # "put" (bearish) or "call" (bullish)
    leg: OptionLeg
    dte: int
    spot_price: float
    cost_per_contract: float = 0.0     # = leg.ask * 100 — this IS the max loss
    cost_pct: Optional[float] = None
    profit_target_low: float = 0.0     # sell-to-close price at +50% gain
    profit_target_high: float = 0.0    # sell-to-close price at +100% gain
    stop_loss_high: float = 0.0        # sell-to-close price at -40% loss
    stop_loss_low: float = 0.0         # sell-to-close price at -50% loss
    time_stop_date: str = ""           # = expiration itself — flatten regardless of P/L
    checklist: list[ChecklistItem] = field(default_factory=list)
    confidence_score: float = 0.0      # 0-100, capped when IV Rank unverified
    confidence_stars: int = 0          # 0-5, for display
    overall_status: str = "PENDING"    # "CANDIDATE" or "SKIP"
    warnings: list[str] = field(default_factory=list)


@dataclass
class SpreadCandidate:
    """
    LEGACY (pre-addendum) — multi-leg credit spread candidate. Not used by the active
    code path; kept in case a margin account is opened later and spreads return. See
    docs/strategy-handoff.md and src/strategy.py::find_candidate_spreads (legacy).
    """
    symbol: str
    group: str
    spread_type: str         # "put_credit" or "call_credit"
    short_leg: OptionLeg
    long_leg: OptionLeg
    dte: int
    spot_price: float
    strike_width: float
    credit: float = 0.0
    max_risk_per_contract: float = 0.0
    max_risk_pct: Optional[float] = None
    profit_target_debit: float = 0.0
    stop_loss_debit: float = 0.0
    time_stop_date: str = ""
    checklist: list[ChecklistItem] = field(default_factory=list)
    confidence_score: float = 0.0
    confidence_stars: int = 0
    overall_status: str = "PENDING"
    warnings: list[str] = field(default_factory=list)
