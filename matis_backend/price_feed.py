# price_feed.py — Centralized CoinDCX Price Fetcher with Rate-Limit Backoff + WebSocket Broadcaster
import asyncio
import json
import logging
from typing import Set
from datetime import datetime, timezone

import httpx
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("price_feed")

COINDCX_TICKER_URL = "https://api.coindcx.com/exchange/ticker"

# Internal asset names → CoinDCX market symbols
COINDCX_MARKETS = {
    "BTC": "BTCINR",
    "ETH": "ETHINR",
    "SOL": "SOLINR",
    "XRP": "XRPINR",
    "BNB": "BNBINR",
    "LINK": "LINKINR",
    "USDT": "USDTINR",
}

# Reverse lookup
_MARKET_TO_ASSET = {v: k for k, v in COINDCX_MARKETS.items()}

# Global in-memory price store
live_prices: dict = {}

# Connected WebSocket clients
_ws_clients: Set[WebSocket] = set()


class CoinDCXPriceFeed:
    """
    Background async price fetcher for CoinDCX.
    - Fetches every `interval` seconds
    - Exponential backoff on HTTP 429 or network errors (2s → 4s → 8s → 16s max)
    - Broadcasts to all connected WebSocket clients
    """

    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self._backoff = 0.0
        self._max_backoff = 16.0
        self._base_backoff = 2.0
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """Start the background fetch loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._fetch_loop())
        logger.info("[PRICE FEED] CoinDCX background fetcher started (interval=%ss)", self.interval)
        print(f"[PRICE FEED] CoinDCX background fetcher started (interval={self.interval}s)")

    async def stop(self):
        """Stop the background fetch loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[PRICE FEED] CoinDCX background fetcher stopped")
        print("[PRICE FEED] CoinDCX background fetcher stopped")

    async def _fetch_loop(self):
        """Main async loop: fetch → parse → broadcast → sleep."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            while self._running:
                try:
                    resp = await client.get(COINDCX_TICKER_URL)

                    # Handle rate limiting
                    if resp.status_code == 429:
                        self._increase_backoff()
                        logger.warning(
                            "[PRICE FEED] HTTP 429 — Rate limited. Backing off %.1fs",
                            self._backoff
                        )
                        print(f"[PRICE FEED] ⚠️ HTTP 429 — Rate limited. Backing off {self._backoff:.1f}s")
                        await asyncio.sleep(self._backoff)
                        continue

                    resp.raise_for_status()
                    data = resp.json()
                    self._reset_backoff()

                    # Parse ticker data — extract only our tracked INR markets
                    updated_prices = {}
                    for ticker in data:
                        market = ticker.get("market", "")
                        if market in _MARKET_TO_ASSET:
                            asset_name = _MARKET_TO_ASSET[market]
                            last_price = float(ticker.get("last_price", 0))
                            change_24h = float(ticker.get("change_24_hour", 0))
                            high_24h = float(ticker.get("high", 0))
                            low_24h = float(ticker.get("low", 0))
                            volume = float(ticker.get("volume", 0))

                            updated_prices[asset_name] = {
                                "market": market,
                                "price_inr": last_price,
                                "change_24h": change_24h,
                                "high_24h": high_24h,
                                "low_24h": low_24h,
                                "volume": volume,
                                "updated_at": datetime.now(timezone.utc).isoformat()
                            }

                    # Update global store
                    live_prices.update(updated_prices)

                    # Broadcast to WebSocket clients
                    await self._broadcast(updated_prices)

                except httpx.HTTPStatusError as e:
                    self._increase_backoff()
                    logger.error("[PRICE FEED] HTTP error %s. Backoff %.1fs", e.response.status_code, self._backoff)
                    print(f"[PRICE FEED] ⚠️ HTTP {e.response.status_code}. Backoff {self._backoff:.1f}s")
                    await asyncio.sleep(self._backoff)
                    continue

                except (httpx.RequestError, Exception) as e:
                    self._increase_backoff()
                    logger.error("[PRICE FEED] Network error: %s. Backoff %.1fs", str(e), self._backoff)
                    print(f"[PRICE FEED] ⚠️ Network error: {e}. Backoff {self._backoff:.1f}s")
                    await asyncio.sleep(self._backoff)
                    continue

                await asyncio.sleep(self.interval)

    def _increase_backoff(self):
        """Exponential backoff: 2 → 4 → 8 → 16 (capped)."""
        if self._backoff == 0:
            self._backoff = self._base_backoff
        else:
            self._backoff = min(self._backoff * 2, self._max_backoff)

    def _reset_backoff(self):
        """Reset backoff on successful fetch."""
        self._backoff = 0.0

    async def _broadcast(self, prices: dict):
        """Send price update to all connected WebSocket clients."""
        if not _ws_clients:
            return
        message = json.dumps({"type": "price_update", "prices": prices})
        stale = set()
        for ws in _ws_clients:
            try:
                await ws.send_text(message)
            except Exception:
                stale.add(ws)
        _ws_clients.difference_update(stale)


def get_inr_price(asset: str) -> float:
    """Get the latest INR price for an asset from the global store."""
    entry = live_prices.get(asset, {})
    return entry.get("price_inr", 0.0)

def get_usd_to_inr_rate() -> float:
    """Get the current USD to INR conversion rate from USDTINR market."""
    rate = get_inr_price("USDT")
    return rate if rate > 0 else 84.0


async def ws_price_handler(websocket: WebSocket):
    """
    WebSocket endpoint handler for /ws/prices.
    Accepts the connection and keeps it alive; prices are pushed via broadcast.
    """
    await websocket.accept()
    _ws_clients.add(websocket)
    print(f"[WS] Client connected. Total: {len(_ws_clients)}")
    try:
        # Send current prices immediately on connect
        if live_prices:
            await websocket.send_text(json.dumps({"type": "price_update", "prices": live_prices}))
        # Keep connection alive — just listen for pings/close
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_clients.discard(websocket)
        print(f"[WS] Client disconnected. Total: {len(_ws_clients)}")


# Singleton instance
price_feed = CoinDCXPriceFeed(interval=5.0)
