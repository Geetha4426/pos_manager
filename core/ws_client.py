"""
WebSocket Client for Polymarket CLOB

Real-time price updates via WebSocket connection.
"""

import asyncio
import json
from typing import Dict, Callable, Optional, Set
from datetime import datetime

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    print("⚠️ websockets not installed - run: pip install websockets")

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


class PriceWebSocketClient:
    """
    WebSocket client for real-time price updates from Polymarket CLOB.
    """
    
    # Polymarket CLOB WebSocket endpoint
    WS_URL = "wss://clob.polymarket.com/ws"
    
    def __init__(self):
        self._ws = None
        self._running = False
        self._subscribed_tokens: Set[str] = set()
        self._price_cache: Dict[str, float] = {}
        self._callbacks: list = []
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
    
    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.open
    
    def get_cached_price(self, token_id: str) -> Optional[float]:
        """Get cached price for a token."""
        return self._price_cache.get(token_id)
    
    def add_price_callback(self, callback: Callable[[str, float], None]):
        """Add callback to be called on price updates."""
        self._callbacks.append(callback)
    
    async def subscribe(self, token_id: str):
        """Subscribe to price updates for a token."""
        self._subscribed_tokens.add(token_id)
        
        if self.is_connected:
            await self._send_subscribe(token_id)
    
    async def unsubscribe(self, token_id: str):
        """Unsubscribe from price updates for a token."""
        self._subscribed_tokens.discard(token_id)
        
        if self.is_connected:
            await self._send_unsubscribe(token_id)
    
    async def _send_subscribe(self, token_id: str):
        """Send subscribe message to WebSocket."""
        if not self._ws:
            return
        
        try:
            msg = {
                "type": "subscribe",
                "channel": "price",
                "assets": [token_id]
            }
            await self._ws.send(json.dumps(msg))
            print(f"📡 Subscribed to price updates for {token_id[:12]}...")
        except Exception as e:
            print(f"⚠️ Subscribe error: {e}")
    
    async def _send_unsubscribe(self, token_id: str):
        """Send unsubscribe message to WebSocket."""
        if not self._ws:
            return
        
        try:
            msg = {
                "type": "unsubscribe",
                "channel": "price",
                "assets": [token_id]
            }
            await self._ws.send(json.dumps(msg))
        except Exception as e:
            print(f"⚠️ Unsubscribe error: {e}")
    
    async def connect(self):
        """Connect to WebSocket and start receiving messages."""
        if not WEBSOCKETS_AVAILABLE:
            print("❌ WebSocket not available - websockets package not installed")
            return
        
        self._running = True
        
        while self._running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    self._ws = ws
                    self._reconnect_delay = 1
                    print("✅ WebSocket connected to Polymarket CLOB")
                    
                    # Resubscribe to all tokens
                    for token_id in self._subscribed_tokens:
                        await self._send_subscribe(token_id)
                    
                    # Message loop
                    async for message in ws:
                        await self._handle_message(message)
                        
            except websockets.ConnectionClosed as e:
                print(f"⚠️ WebSocket connection closed: {e}")
            except Exception as e:
                print(f"⚠️ WebSocket error: {e}")
            
            self._ws = None
            
            if self._running:
                print(f"⏳ Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            
            msg_type = data.get('type', '')
            
            if msg_type == 'price_update' or 'price' in data:
                token_id = data.get('asset_id', data.get('token_id', ''))
                price = data.get('price', data.get('mid', 0))
                
                if token_id and price:
                    self._price_cache[token_id] = float(price)
                    
                    # Call callbacks
                    for callback in self._callbacks:
                        try:
                            await callback(token_id, float(price))
                        except Exception as e:
                            print(f"⚠️ Callback error: {e}")
            
            elif msg_type == 'book_update':
                # Order book update
                token_id = data.get('asset_id', '')
                bids = data.get('bids', [])
                asks = data.get('asks', [])
                
                # Calculate midpoint from order book
                if bids and asks:
                    best_bid = float(bids[0]['price']) if isinstance(bids[0], dict) else float(bids[0][0])
                    best_ask = float(asks[0]['price']) if isinstance(asks[0], dict) else float(asks[0][0])
                    mid = (best_bid + best_ask) / 2
                    self._price_cache[token_id] = mid
                    
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"⚠️ Message handling error: {e}")
    
    async def disconnect(self):
        """Disconnect from WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        print("🔌 WebSocket disconnected")
    
    def get_all_cached_prices(self) -> Dict[str, float]:
        """Get all cached prices."""
        return self._price_cache.copy()


# Singleton instance
_ws_client: Optional[PriceWebSocketClient] = None

def get_ws_client() -> PriceWebSocketClient:
    """Get the WebSocket client singleton."""
    global _ws_client
    if _ws_client is None:
        _ws_client = PriceWebSocketClient()
    return _ws_client


async def start_price_monitor(bot=None):
    """
    Start the WebSocket price monitor.
    Optionally pass bot instance for notifications.
    """
    client = get_ws_client()
    
    if bot:
        # Add callback to check alerts on price updates
        async def check_alerts(token_id: str, price: float):
            from core.alerts import get_alert_manager
            manager = get_alert_manager()
            alerts = await manager.get_alerts(active_only=True)
            
            for alert in alerts:
                if alert.token_id != token_id:
                    continue
                
                triggered = False
                if alert.side == 'above' and price >= alert.trigger_price:
                    triggered = True
                elif alert.side == 'below' and price <= alert.trigger_price:
                    triggered = True
                
                if triggered:
                    await manager.mark_triggered(alert.id)
                    # TODO: Send Telegram notification
                    print(f"🔔 Alert triggered! {alert.market_question} @ {price*100:.0f}¢")
        
        client.add_price_callback(check_alerts)
    
    await client.connect()
