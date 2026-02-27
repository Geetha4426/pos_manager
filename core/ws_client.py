"""
WebSocket Client for Polymarket CLOB

Real-time price & orderbook updates via WebSocket.
Based on Polymarket official WS protocol + 5min_trade patterns.

Supports:
- Token subscription with assets_ids (correct Polymarket protocol)
- Price change events, book snapshots, last trade price
- Best bid/ask tracking with PriceSnapshot objects
- Automatic reconnection with exponential backoff
- Callbacks for price updates (position tracking, alerts)
- Integration with Telegram for live position updates
"""

import asyncio
import json
import time
from typing import Dict, Callable, Optional, Set, List
from dataclasses import dataclass
from collections import deque

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


@dataclass
class PriceSnapshot:
    """Point-in-time price data with bid/ask."""
    token_id: str
    price: float
    best_bid: float
    best_ask: float
    spread: float
    timestamp: float
    
    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2
        return self.price
    
    @property
    def spread_pct(self) -> float:
        if self.best_ask > 0:
            return (self.spread / self.best_ask) * 100
        return 0.0


class PolymarketWebSocket:
    """
    WebSocket client for real-time Polymarket CLOB data.
    
    Uses the correct Polymarket WS protocol:
    - Subscribe: {"assets_ids": [...], "type": "market"}
    - Receives: initial snapshots, price_change events, book updates
    """
    
    WS_URL = getattr(Config, 'POLYMARKET_WS_URL', 'wss://ws-subscriptions-clob.polymarket.com/ws/market')
    
    def __init__(self):
        self._ws = None
        self._running = False
        self._subscribed_tokens: Set[str] = set()
        
        # Price data
        self._price_cache: Dict[str, PriceSnapshot] = {}
        self._price_history: Dict[str, deque] = {}
        
        # Callbacks
        self._price_callbacks: List[Callable] = []
        self._position_callbacks: List[Callable] = []
        
        # Reconnection
        self._reconnect_delay = 1
        self._max_reconnect_delay = 30
        self._connected = False
        
        # Stats
        self._msg_count = 0
        self._last_msg_time = 0
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None
    
    def get_snapshot(self, token_id: str) -> Optional[PriceSnapshot]:
        """Get latest price snapshot for a token."""
        return self._price_cache.get(token_id)
    
    def get_price(self, token_id: str) -> Optional[float]:
        """Get cached price for a token."""
        snap = self._price_cache.get(token_id)
        return snap.price if snap else None
    
    def get_best_bid(self, token_id: str) -> Optional[float]:
        """Get best bid price (what you get when selling)."""
        snap = self._price_cache.get(token_id)
        return snap.best_bid if snap else None
    
    def get_best_ask(self, token_id: str) -> Optional[float]:
        """Get best ask price."""
        snap = self._price_cache.get(token_id)
        return snap.best_ask if snap else None
    
    def get_spread(self, token_id: str) -> Optional[float]:
        """Get current spread."""
        snap = self._price_cache.get(token_id)
        return snap.spread if snap else None
    
    def get_price_history(self, token_id: str, limit: int = 60) -> List[PriceSnapshot]:
        """Get price history for a token."""
        history = self._price_history.get(token_id)
        if history:
            return list(history)[-limit:]
        return []
    
    def get_all_prices(self) -> Dict[str, PriceSnapshot]:
        """Get all cached price snapshots."""
        return self._price_cache.copy()
    
    # Legacy compatibility
    def get_cached_price(self, token_id: str) -> Optional[float]:
        return self.get_price(token_id)
    
    def get_all_cached_prices(self) -> Dict[str, float]:
        return {tid: snap.price for tid, snap in self._price_cache.items()}
    
    def add_price_callback(self, callback):
        """Legacy: add callback(token_id, price)."""
        async def wrapper(snap: PriceSnapshot):
            await callback(snap.token_id, snap.price)
        self._price_callbacks.append(wrapper)
    
    # ═══════════════════════════════════════════════════════════════════
    # CALLBACKS
    # ═══════════════════════════════════════════════════════════════════
    
    def on_price_update(self, callback: Callable):
        """Register callback: async def callback(snapshot: PriceSnapshot)"""
        self._price_callbacks.append(callback)
    
    def on_position_update(self, callback: Callable):
        """Register callback for position-relevant price changes."""
        self._position_callbacks.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════
    # SUBSCRIPTION
    # ═══════════════════════════════════════════════════════════════════
    
    async def subscribe(self, token_ids):
        """Subscribe to price updates for tokens. Accepts str or list."""
        if isinstance(token_ids, str):
            token_ids = [token_ids]
        
        new_tokens = set(token_ids) - self._subscribed_tokens
        self._subscribed_tokens.update(token_ids)
        
        for tid in new_tokens:
            if tid not in self._price_history:
                self._price_history[tid] = deque(maxlen=120)
        
        if self.is_connected and new_tokens:
            await self._send_subscribe(list(new_tokens))
    
    async def unsubscribe(self, token_ids):
        """Unsubscribe from tokens."""
        if isinstance(token_ids, str):
            token_ids = [token_ids]
        for tid in token_ids:
            self._subscribed_tokens.discard(tid)
    
    async def _send_subscribe(self, token_ids: List[str]):
        """Send subscription using correct Polymarket WS protocol."""
        if not self._ws or not token_ids:
            return
        try:
            sub_msg = json.dumps({
                "assets_ids": token_ids,
                "type": "market",
            })
            await self._ws.send(sub_msg)
            print(f"📡 WS subscribed to {len(token_ids)} tokens")
        except Exception as e:
            print(f"⚠️ WS subscribe error: {e}")
    
    # ═══════════════════════════════════════════════════════════════════
    # CONNECTION
    # ═══════════════════════════════════════════════════════════════════
    
    async def connect(self):
        """Connect to WebSocket and start receiving messages."""
        if not WEBSOCKETS_AVAILABLE:
            print("❌ WebSocket not available - pip install websockets")
            return
        
        self._running = True
        _logged_first = False
        
        while self._running:
            try:
                async with websockets.connect(
                    self.WS_URL,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=10,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_delay = 1
                    print(f"✅ Polymarket WS connected")
                    
                    if self._subscribed_tokens:
                        await self._send_subscribe(list(self._subscribed_tokens))
                    
                    async for message in ws:
                        if not self._running:
                            break
                        if not _logged_first:
                            _logged_first = True
                            preview = message[:200] if len(message) > 200 else message
                            print(f"📨 First WS msg: {preview}")
                        await self._handle_message(message)
                        
            except websockets.ConnectionClosed as e:
                print(f"⚠️ WS disconnected: {e}")
            except Exception as e:
                print(f"⚠️ WS error: {e}")
            
            self._ws = None
            self._connected = False
            
            if self._running:
                print(f"⏳ WS reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
    
    async def _handle_message(self, raw: str):
        """
        Parse WebSocket message. Polymarket CLOB WS sends:
        1. Initial snapshot: list of orderbook objects
        2. price_change events: {"event_type": "price_change", ...}
        3. Individual events with asset_id, price, best_bid, best_ask
        4. last_trade_price events
        """
        try:
            data = json.loads(raw)
            self._msg_count += 1
            self._last_msg_time = time.time()
            
            # Format 1: Initial snapshot — list of orderbook entries
            if isinstance(data, list):
                for entry in data:
                    asset_id = entry.get('asset_id', '')
                    if not asset_id:
                        continue
                    bids = entry.get('bids', [])
                    asks = entry.get('asks', [])
                    best_bid = 0.0
                    best_ask = 0.0
                    if bids:
                        bid_prices = [float(b.get('price', b.get('p', 0))) for b in bids]
                        bid_prices = [p for p in bid_prices if 0 < p <= 1.0]
                        best_bid = max(bid_prices) if bid_prices else 0.0
                    if asks:
                        ask_prices = [float(a.get('price', a.get('p', 0))) for a in asks]
                        ask_prices = [p for p in ask_prices if 0 < p <= 1.0]
                        best_ask = min(ask_prices) if ask_prices else 0.0
                    if best_bid > 0 or best_ask > 0:
                        price = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else (best_ask or best_bid)
                        await self._apply_price(asset_id, price, best_bid, best_ask)
                return
            
            # Format 2: price_change event
            event_type = data.get('event_type', '')
            if event_type == 'price_change':
                for ch in data.get('price_changes', []):
                    asset_id = ch.get('asset_id', '')
                    if not asset_id:
                        continue
                    best_bid = float(ch.get('best_bid', 0))
                    best_ask = float(ch.get('best_ask', 0))
                    price = float(ch.get('price', 0))
                    if not price and best_ask > 0:
                        price = best_ask
                    elif not price and best_bid > 0 and best_ask > 0:
                        price = (best_bid + best_ask) / 2
                    if price > 0:
                        await self._apply_price(asset_id, price, best_bid, best_ask)
                return
            
            # Format 3: Individual book/trade updates
            msg_type = data.get('type', data.get('event_type', ''))
            if msg_type in ('book', 'price_change', 'last_trade_price', 'tick_size_change'):
                token_id = data.get('asset_id', data.get('market', ''))
                if not token_id:
                    return
                price = float(data.get('price', data.get('last_trade_price', data.get('mid', 0))))
                best_bid = float(data.get('best_bid', 0))
                best_ask = float(data.get('best_ask', 0))
                if price <= 0 and best_ask > 0:
                    price = best_ask
                elif price <= 0 and best_bid > 0 and best_ask > 0:
                    price = (best_bid + best_ask) / 2
                if price > 0:
                    await self._apply_price(token_id, price, best_bid, best_ask)
            
            # Format 4: Legacy price_update
            elif data.get('type') == 'price_update' or ('price' in data and 'asset_id' in data):
                token_id = data.get('asset_id', data.get('token_id', ''))
                price = float(data.get('price', data.get('mid', 0)))
                if token_id and price > 0:
                    await self._apply_price(token_id, price)
                    
        except json.JSONDecodeError:
            pass
        except Exception:
            pass
    
    async def _apply_price(self, token_id: str, price: float,
                           best_bid: float = 0, best_ask: float = 0):
        """Store price update and trigger all callbacks."""
        # Sanity: Polymarket prices are always 0-1 decimal
        if price <= 0 or price > 1.0:
            return
        if best_ask <= 0:
            best_ask = price
        if best_bid <= 0:
            best_bid = max(0, price - 0.01)
        spread = best_ask - best_bid if best_ask > best_bid else 0
        
        snap = PriceSnapshot(
            token_id=token_id, price=price,
            best_bid=best_bid, best_ask=best_ask,
            spread=spread, timestamp=time.time()
        )
        
        self._price_cache[token_id] = snap
        
        if token_id in self._price_history:
            self._price_history[token_id].append(snap)
        elif token_id in self._subscribed_tokens:
            self._price_history[token_id] = deque(maxlen=120)
            self._price_history[token_id].append(snap)
        
        for callback in self._price_callbacks:
            try:
                await callback(snap)
            except Exception:
                pass
        
        if token_id in self._subscribed_tokens:
            for callback in self._position_callbacks:
                try:
                    await callback(snap)
                except Exception:
                    pass
    
    async def disconnect(self):
        """Disconnect from WebSocket."""
        self._running = False
        self._connected = False
        if self._ws:
            try:
                await self._ws.close()
            except:
                pass
            self._ws = None
        print("🔌 WS disconnected")
    
    def get_stats(self) -> Dict:
        return {
            'connected': self.is_connected,
            'subscribed_tokens': len(self._subscribed_tokens),
            'cached_prices': len(self._price_cache),
            'total_messages': self._msg_count,
        }


# ═══════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════

_ws_client: Optional[PolymarketWebSocket] = None

def get_ws_client() -> PolymarketWebSocket:
    """Get the WebSocket client singleton."""
    global _ws_client
    if _ws_client is None:
        _ws_client = PolymarketWebSocket()
    return _ws_client


# Legacy alias
PriceWebSocketClient = PolymarketWebSocket


async def start_price_monitor(bot=None):
    """Start the WebSocket price feed with optional Telegram alerts and auto-execution."""
    client = get_ws_client()
    
    if bot:
        # Track recently executed alerts to avoid duplicates
        _executed_alerts = set()
        # Cache alerts to avoid SQLite query on every WS tick
        _cached_alerts = []
        _alert_cache_time = 0
        _ALERT_CACHE_TTL = 5  # seconds
        
        async def check_alerts(snap: PriceSnapshot):
            nonlocal _cached_alerts, _alert_cache_time
            try:
                # Skip invalid prices \u2014 prevents false SL/TP triggers from WS glitches
                if snap.price < 0.01 or snap.price > 0.99:
                    return
                from core.alerts import get_alert_manager, AlertType
                manager = get_alert_manager()
                
                # Refresh cache every N seconds instead of every tick
                now = time.time()
                if now - _alert_cache_time > _ALERT_CACHE_TTL:
                    _cached_alerts = await manager.get_alerts(active_only=True)
                    _alert_cache_time = now
                
                for alert in _cached_alerts:
                    if alert.token_id != snap.token_id:
                        continue
                    if alert.id in _executed_alerts:
                        continue
                    triggered = False
                    if alert.side == 'above' and snap.price >= alert.trigger_price:
                        triggered = True
                    elif alert.side == 'below' and snap.price <= alert.trigger_price:
                        triggered = True
                    if triggered:
                        await manager.mark_triggered(alert.id)
                        _executed_alerts.add(alert.id)
                        
                        chat_id = alert.user_id or Config.TELEGRAM_CHAT_ID
                        
                        # Auto-execute sell for stop-loss and take-profit
                        if alert.auto_trade and alert.alert_type in (AlertType.STOP_LOSS, AlertType.TAKE_PROFIT):
                            try:
                                from core.polymarket_client import get_user_client as get_pm_user_client
                                
                                user_id = int(alert.user_id)
                                user_client = get_pm_user_client(user_id)
                                
                                if user_client:
                                    # Execute instant sell 100%
                                    result = await user_client.instant_sell(alert.token_id, percent=100)
                                    
                                    type_label = "🛑 Stop Loss" if alert.alert_type == AlertType.STOP_LOSS else "🎯 Take Profit"
                                    
                                    if result.success:
                                        proceeds = result.filled_size * result.avg_price if result.avg_price > 0 else 0
                                        text = (
                                            f"{type_label} <b>EXECUTED!</b>\n\n"
                                            f"📋 {alert.market_question[:50]}\n"
                                            f"📍 Trigger: {alert.trigger_price*100:.0f}¢\n"
                                            f"📦 Sold: {result.filled_size:.1f} shares\n"
                                            f"💵 Price: {result.avg_price*100:.1f}¢\n"
                                            f"💰 Proceeds: ${proceeds:.2f}\n"
                                        )
                                        if result.order_id:
                                            text += f"🆔 <code>{result.order_id[:16]}...</code>"
                                        print(f"⚡ Auto-sell executed for alert {alert.id}: {result.filled_size} shares")
                                    else:
                                        text = (
                                            f"{type_label} <b>TRIGGERED but SELL FAILED</b>\n\n"
                                            f"📋 {alert.market_question[:50]}\n"
                                            f"📍 Trigger: {alert.trigger_price*100:.0f}¢\n"
                                            f"❌ Error: {result.error}\n\n"
                                            f"<i>Use /positions to sell manually.</i>"
                                        )
                                        print(f"❌ Auto-sell failed for alert {alert.id}: {result.error}")
                                    
                                    if chat_id:
                                        await bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
                                else:
                                    # Session not active — notify but can't execute
                                    type_label = "🛑 Stop Loss" if alert.alert_type == AlertType.STOP_LOSS else "🎯 Take Profit"
                                    if chat_id:
                                        await bot.send_message(
                                            chat_id=chat_id,
                                            text=(
                                                f"{type_label} <b>TRIGGERED — ⚠️ NO SESSION</b>\n\n"
                                                f"📋 {alert.market_question[:50]}\n"
                                                f"📍 Price: {snap.price*100:.0f}¢ hit {alert.trigger_price*100:.0f}¢\n\n"
                                                f"⚠️ Could not auto-sell: wallet not unlocked.\n"
                                                f"Use /unlock then /positions to sell manually."
                                            ),
                                            parse_mode='HTML'
                                        )
                            except Exception as e:
                                print(f"❌ Auto-sell exception for alert {alert.id}: {e}")
                                if chat_id:
                                    try:
                                        await bot.send_message(
                                            chat_id=chat_id,
                                            text=f"⚠️ Alert triggered but auto-sell error: {e}",
                                        )
                                    except Exception:
                                        pass
                        else:
                            # Regular price alert — just notify
                            try:
                                if chat_id:
                                    emoji = "🔔" if alert.side == 'above' else "🔻"
                                    text = (
                                        f"{emoji} <b>Alert Triggered!</b>\n\n"
                                        f"📋 {alert.market_question}\n"
                                        f"📍 Price: {snap.price*100:.0f}¢\n"
                                        f"🎯 Target: {alert.trigger_price*100:.0f}¢ ({alert.side})"
                                    )
                                    await bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
                            except Exception:
                                pass
            except Exception:
                pass
        
        client.on_price_update(check_alerts)
    
    await client.connect()
