"""
Real-Time Position Manager

Tracks positions with live WebSocket prices, calculates P&L in real-time,
and pushes updates to Telegram messages (edit-in-place).

Features:
- Auto-subscribe to WS for all position token IDs
- Live P&L with fee-aware calculations
- Push updates to Telegram (edit message with fresh prices)
- Instant sell integration
- Dynamic fee calculation (from 5min_trade pattern)
"""

import asyncio
import time
from typing import Dict, Optional, List, Callable
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


# Dynamic fee: peaks at 50% price, drops at extremes
BASE_FEE = 0.0156  # ~1.56% base fee for most markets

def calc_fee(price: float) -> float:
    """Calculate dynamic Polymarket fee for a given price."""
    return BASE_FEE * 4 * price * (1 - price)

def calc_fee_adjusted_pnl(avg_price: float, current_bid: float, size: float) -> float:
    """Calculate P&L accounting for buy+sell fees."""
    buy_fee = calc_fee(avg_price)
    sell_fee = calc_fee(current_bid)
    effective_buy = avg_price * (1 + buy_fee)
    effective_sell = current_bid * (1 - sell_fee)
    return (effective_sell - effective_buy) * size


@dataclass
class LivePosition:
    """A position with real-time price data."""
    token_id: str
    condition_id: str
    question: str
    outcome: str
    size: float
    avg_price: float
    # Live data (updated by WS)
    current_price: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    last_update: float = 0.0
    
    @property
    def value(self) -> float:
        price = self.best_bid if self.best_bid > 0 else self.current_price
        return price * self.size
    
    @property
    def cost_basis(self) -> float:
        return self.avg_price * self.size
    
    @property
    def pnl(self) -> float:
        """Raw P&L (no fees)."""
        sell_price = self.best_bid if self.best_bid > 0 else self.current_price
        return (sell_price - self.avg_price) * self.size
    
    @property
    def pnl_with_fees(self) -> float:
        """P&L accounting for buy+sell fees."""
        sell_price = self.best_bid if self.best_bid > 0 else self.current_price
        if sell_price <= 0 or self.avg_price <= 0:
            return 0.0
        return calc_fee_adjusted_pnl(self.avg_price, sell_price, self.size)
    
    @property
    def pnl_percent(self) -> float:
        if self.cost_basis <= 0:
            return 0.0
        return (self.pnl / self.cost_basis) * 100
    
    @property
    def is_stale(self) -> bool:
        """True if price data is older than 30 seconds."""
        return (time.time() - self.last_update) > 30 if self.last_update > 0 else True
    
    def format_pnl(self) -> str:
        """Format P&L with color emoji."""
        pnl = self.pnl
        pct = self.pnl_percent
        if pnl >= 0:
            return f"🟢 +${pnl:.2f} (+{pct:.1f}%)"
        else:
            return f"🔴 -${abs(pnl):.2f} ({pct:.1f}%)"
    
    def format_summary(self) -> str:
        """Format position as a compact summary line."""
        bid_str = f"{self.best_bid*100:.1f}¢" if self.best_bid > 0 else f"{self.current_price*100:.1f}¢"
        return (
            f"📋 {self.question[:50]}\n"
            f"   {self.outcome} | {self.size:.1f} shares @ {self.avg_price*100:.1f}¢\n"
            f"   💰 Value: ${self.value:.2f} | {self.format_pnl()}\n"
            f"   📊 Bid: {bid_str} | Spread: {self.spread*100:.1f}¢"
        )


class PositionManager:
    """
    Manages positions with real-time WS price updates.
    
    Usage:
        manager = get_position_manager()
        await manager.load_positions()  # fetch from CLOB
        manager.start_tracking()        # subscribe to WS
    """
    
    def __init__(self):
        self._positions: Dict[str, LivePosition] = {}
        self._tracking = False
        self._update_callbacks: List[Callable] = []
        self._last_full_refresh = 0
        self._refresh_interval = float(getattr(Config, 'POSITION_REFRESH_INTERVAL', 10))
    
    @property
    def positions(self) -> Dict[str, LivePosition]:
        return self._positions
    
    def get_position(self, token_id: str) -> Optional[LivePosition]:
        return self._positions.get(token_id)
    
    def get_all_positions(self) -> List[LivePosition]:
        return list(self._positions.values())
    
    def get_total_value(self) -> float:
        return sum(p.value for p in self._positions.values())
    
    def get_total_pnl(self) -> float:
        return sum(p.pnl for p in self._positions.values())
    
    def get_total_pnl_with_fees(self) -> float:
        return sum(p.pnl_with_fees for p in self._positions.values())
    
    def on_update(self, callback: Callable):
        """Register callback: async def callback(position: LivePosition)"""
        self._update_callbacks.append(callback)
    
    async def load_positions(self):
        """Fetch positions from CLOB/paper and populate live tracking."""
        try:
            from core.polymarket_client import get_polymarket_client
            client = get_polymarket_client()
            positions = await client.get_positions()
            
            # Replace entire cache — removes closed/settled positions
            new_positions = {}
            for pos in positions:
                new_positions[pos.token_id] = LivePosition(
                    token_id=pos.token_id,
                    condition_id=pos.condition_id,
                    question=pos.market_question,
                    outcome=pos.outcome,
                    size=pos.size,
                    avg_price=pos.avg_price,
                    current_price=pos.current_price,
                    best_bid=pos.current_price,
                    last_update=time.time(),
                )
            self._positions = new_positions
            
            print(f"📦 Loaded {len(self._positions)} positions for tracking")
        except Exception as e:
            print(f"⚠️ Position load error: {e}")
    
    async def start_tracking(self):
        """Subscribe to WS for all position tokens."""
        if self._tracking:
            return
        self._tracking = True
        
        try:
            from core.ws_client import get_ws_client
            ws = get_ws_client()
            
            # Subscribe to all position tokens
            token_ids = list(self._positions.keys())
            if token_ids:
                await ws.subscribe(token_ids)
                print(f"📡 WS tracking {len(token_ids)} position tokens")
            
            # Register price callback
            ws.on_position_update(self._on_price_update)
            
        except Exception as e:
            print(f"⚠️ WS tracking start error: {e}")
    
    async def _on_price_update(self, snapshot):
        """Handle WS price update for a tracked position."""
        pos = self._positions.get(snapshot.token_id)
        if not pos:
            return
        
        # Update live data
        pos.current_price = snapshot.price
        pos.best_bid = snapshot.best_bid
        pos.best_ask = snapshot.best_ask
        pos.spread = snapshot.spread
        pos.last_update = snapshot.timestamp
        
        # Fire callbacks
        for cb in self._update_callbacks:
            try:
                await cb(pos)
            except Exception:
                pass
    
    async def add_position(self, token_id: str, condition_id: str,
                           question: str, outcome: str, size: float,
                           avg_price: float, current_price: float = 0):
        """Add a new position and start WS tracking."""
        self._positions[token_id] = LivePosition(
            token_id=token_id,
            condition_id=condition_id,
            question=question,
            outcome=outcome,
            size=size,
            avg_price=avg_price,
            current_price=current_price or avg_price,
            best_bid=current_price or avg_price,
            last_update=time.time(),
        )
        
        # Subscribe to WS for this token
        try:
            from core.ws_client import get_ws_client
            ws = get_ws_client()
            await ws.subscribe(token_id)
        except Exception:
            pass
    
    async def remove_position(self, token_id: str):
        """Remove a position (after selling)."""
        self._positions.pop(token_id, None)
    
    async def update_position_size(self, token_id: str, new_size: float):
        """Update position size (after partial sell)."""
        pos = self._positions.get(token_id)
        if pos:
            if new_size <= 0.001:
                await self.remove_position(token_id)
            else:
                pos.size = new_size
    
    async def refresh_all_prices(self):
        """Force refresh all prices from CLOB REST (fallback if WS slow)."""
        try:
            from core.polymarket_client import get_polymarket_client
            client = get_polymarket_client()
            
            for token_id, pos in self._positions.items():
                try:
                    price = await client.get_price(token_id)
                    if price > 0:
                        pos.current_price = price
                        if pos.best_bid <= 0:
                            pos.best_bid = price
                        pos.last_update = time.time()
                except Exception:
                    pass
            
            self._last_full_refresh = time.time()
        except Exception as e:
            print(f"⚠️ Price refresh error: {e}")
    
    def format_portfolio_summary(self) -> str:
        """Format all positions as a Telegram message."""
        if not self._positions:
            return "📭 No open positions"
        
        total_value = self.get_total_value()
        total_pnl = self.get_total_pnl()
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        
        lines = [
            f"📊 <b>Portfolio</b> | {len(self._positions)} positions",
            f"💰 Value: <b>${total_value:.2f}</b>",
            f"{pnl_emoji} P&L: <b>${total_pnl:+.2f}</b>",
            "",
        ]
        
        for pos in sorted(self._positions.values(), key=lambda p: abs(p.pnl), reverse=True):
            bid_price = pos.best_bid if pos.best_bid > 0 else pos.current_price
            pnl_str = f"+${pos.pnl:.2f}" if pos.pnl >= 0 else f"-${abs(pos.pnl):.2f}"
            pnl_pct = f"+{pos.pnl_percent:.1f}%" if pos.pnl_percent >= 0 else f"{pos.pnl_percent:.1f}%"
            emoji = "🟢" if pos.pnl >= 0 else "🔴"
            stale = " ⏳" if pos.is_stale else ""
            
            lines.append(
                f"{emoji} <b>{pos.question[:45]}</b>\n"
                f"   {pos.outcome} • {pos.size:.1f}sh @ {pos.avg_price*100:.0f}¢ → {bid_price*100:.0f}¢\n"
                f"   💰 ${pos.value:.2f} | {pnl_str} ({pnl_pct}){stale}"
            )
            lines.append("")
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════

_position_manager: Optional[PositionManager] = None

def get_position_manager() -> PositionManager:
    """Get the position manager singleton."""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager

async def init_position_manager() -> PositionManager:
    """Initialize position manager: load positions + start WS tracking."""
    manager = get_position_manager()
    await manager.load_positions()
    await manager.start_tracking()
    return manager
