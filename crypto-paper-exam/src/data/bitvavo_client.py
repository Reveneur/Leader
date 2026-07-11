"""Thin client for Bitvavo's public REST market-data endpoints. Exam V1
never places real orders, so no API key/secret signing is implemented —
only the public endpoints needed for reference prices, spreads, order-book
depth, and candles (spec section 4.1).
"""
from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://api.bitvavo.com/v2"


class MarketDataError(RuntimeError):
    """Raised on any network/HTTP failure. Callers must catch this and fall
    back to the conservative behavior in spec section 17 (never invent data).
    """


class BitvavoClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 10.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BitvavoClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise MarketDataError(f"GET {path} failed: {exc}") from exc

    def get_markets(self) -> list[dict]:
        return self._get("/markets")

    def get_ticker_price(self, market: str | None = None) -> list[dict]:
        params = {"market": market} if market else None
        result = self._get("/ticker/price", params)
        return result if isinstance(result, list) else [result]

    def get_ticker_book(self, market: str | None = None) -> list[dict]:
        """Best bid/ask per market."""
        params = {"market": market} if market else None
        result = self._get("/ticker/book", params)
        return result if isinstance(result, list) else [result]

    def get_ticker_24h(self, market: str | None = None) -> list[dict]:
        params = {"market": market} if market else None
        result = self._get("/ticker/24h", params)
        return result if isinstance(result, list) else [result]

    def get_candles(
        self,
        market: str,
        interval: str,
        limit: int = 1440,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[list]:
        params: dict[str, Any] = {"limit": limit}
        if start_ms is not None:
            params["start"] = start_ms
        if end_ms is not None:
            params["end"] = end_ms
        return self._get(f"/{market}/candles", {**params, "interval": interval})

    def get_order_book(self, market: str, depth: int = 25) -> dict:
        return self._get(f"/{market}/book", {"depth": depth})
