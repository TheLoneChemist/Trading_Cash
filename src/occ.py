"""
Builds a standard OCC option symbol from an underlying, expiration, type, and strike —
e.g. build_occ_symbol("SPY", "2026-10-16", "put", 736) -> "SPY261016P00736000"

Used by the History page to look up live quotes for legs of a trade that was logged
earlier, since the trade log only stores strike/expiration/type, not the OCC symbol
itself (Tradier's option chain gives you that, but a manually-logged trade wasn't
necessarily read back from a chain response).
"""


def build_occ_symbol(underlying: str, expiration: str, option_type: str, strike: float) -> str:
    yy, mm, dd = expiration[2:4], expiration[5:7], expiration[8:10]
    cp = "C" if option_type == "call" else "P"
    strike_thousandths = round(strike * 1000)
    return f"{underlying.upper()}{yy}{mm}{dd}{cp}{strike_thousandths:08d}"
