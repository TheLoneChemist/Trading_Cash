"""
Thin wrapper around Tradier's market-data endpoints.

Deliberately read-only: this module has no function that places, modifies, or cancels
an order, and no code path in this repo ever calls a Tradier /accounts/.../orders
endpoint. If you extend this later, keep it that way unless you've decided — with full
understanding of the risk — that you actually want auto-execution, which was explicitly
out of scope for this build.
"""
import requests

from . import config


class TradierError(Exception):
    pass


class TradierClient:
    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or config.TRADIER_API_KEY
        self.base_url = base_url or config.TRADIER_BASE_URL
        if not self.api_key:
            raise TradierError(
                "TRADIER_API_KEY is not set. Add it to your .env file or Railway "
                "service variables."
            )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            }
        )

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params or {}, timeout=15)
        except requests.RequestException as e:
            raise TradierError(f"Network error calling Tradier ({path}): {e}") from e
        if resp.status_code == 401:
            raise TradierError("Tradier rejected the API key (401). Check TRADIER_API_KEY.")
        if resp.status_code == 429:
            raise TradierError("Tradier rate limit hit (429). Back off and retry later.")
        if not resp.ok:
            raise TradierError(f"Tradier error {resp.status_code} on {path}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as e:
            raise TradierError(f"Tradier returned non-JSON from {path}: {e}") from e

    def get_quote(self, symbol: str) -> dict:
        """Current quote for the underlying."""
        data = self._get("/markets/quotes", {"symbols": symbol})
        quotes = data.get("quotes", {}).get("quote")
        if quotes is None:
            raise TradierError(f"No quote returned for {symbol}")
        return quotes if isinstance(quotes, dict) else quotes[0]

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """
        Batch quote lookup — works for underlyings or OCC option symbols. Returns a
        dict keyed by the symbol Tradier echoes back, since callers passing a bad/
        delisted option symbol may get fewer results than requested.
        """
        if not symbols:
            return {}
        data = self._get("/markets/quotes", {"symbols": ",".join(symbols)})
        quotes = data.get("quotes", {}).get("quote")
        if quotes is None:
            return {}
        rows = quotes if isinstance(quotes, list) else [quotes]
        return {row["symbol"]: row for row in rows if "symbol" in row}

    def get_expirations(self, symbol: str) -> list[str]:
        """List of available option expiration dates (YYYY-MM-DD) for a symbol."""
        data = self._get(
            "/markets/options/expirations", {"symbol": symbol, "includeAllRoots": "true"}
        )
        exp = data.get("expirations")
        if not exp:
            return []
        dates = exp.get("date")
        if dates is None:
            return []
        return dates if isinstance(dates, list) else [dates]

    def get_option_chain(self, symbol: str, expiration: str) -> list[dict]:
        """Full option chain (calls + puts) for one expiration, with greeks if available."""
        data = self._get(
            "/markets/options/chains",
            {"symbol": symbol, "expiration": expiration, "greeks": "true"},
        )
        options = data.get("options")
        if not options:
            return []
        chain = options.get("option")
        if chain is None:
            return []
        return chain if isinstance(chain, list) else [chain]

    def get_history(self, symbol: str, interval: str = "daily", start: str = None, end: str = None) -> list[dict]:
        """
        Historical daily prices for the underlying. Useful for realized-vol context,
        but note: this is NOT the same as historical implied volatility, and must not
        be substituted for IV Rank — see strategy.py's iv_rank_status().
        """
        params = {"symbol": symbol, "interval": interval}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        data = self._get("/markets/history", params)
        history = data.get("history")
        if not history:
            return []
        day = history.get("day")
        if day is None:
            return []
        return day if isinstance(day, list) else [day]
