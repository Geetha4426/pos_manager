"""
Polymarket Client Wrapper

High-level wrapper around py-clob-client for trading operations.
Supports both paper and live trading modes.
"""

import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import httpx

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        OrderArgs, MarketOrderArgs, OrderType, OpenOrderParams, BookParams
    )
    from py_clob_client.order_builder.constants import BUY, SELL
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("⚠️ py-clob-client not installed - running in mock mode")

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


@dataclass
class Position:
    """Represents a trading position."""
    token_id: str
    condition_id: str
    market_question: str
    outcome: str  # "Yes" or "No"
    size: float  # Number of shares
    avg_price: float  # Average entry price
    current_price: float
    value: float  # Current value in USD
    pnl: float  # Profit/Loss in USD
    pnl_percent: float


@dataclass
class Market:
    """Represents a Polymarket market."""
    condition_id: str
    question: str
    description: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume: float
    category: str
    end_date: Optional[str] = None
    

@dataclass
class OrderResult:
    """Result of a trade execution."""
    success: bool
    order_id: Optional[str] = None
    filled_size: float = 0.0
    avg_price: float = 0.0
    error: Optional[str] = None


class PolymarketClient:
    """
    Unified Polymarket client with high-level trading methods.
    
    Supports:
    - Paper trading (mock execution)
    - Live trading (real Polymarket orders)
    """
    
    def __init__(self):
        self.is_paper = Config.is_paper_mode()
        self.clob_client = None
        self._paper_balance = 1000.0  # Paper trading balance
        self._paper_positions: Dict[str, Dict] = {}
        
        if not self.is_paper and CLOB_AVAILABLE and Config.POLYGON_PRIVATE_KEY:
            self._init_live_client()
        else:
            print(f"📝 Paper trading mode {'(py-clob-client not available)' if not CLOB_AVAILABLE else ''}")
    
    def _init_live_client(self):
        """Initialize live trading client."""
        try:
            self.clob_client = ClobClient(
                Config.POLYMARKET_CLOB_URL,
                key=Config.POLYGON_PRIVATE_KEY,
                chain_id=Config.POLYGON_CHAIN_ID,
                signature_type=Config.SIGNATURE_TYPE,
                funder=Config.FUNDER_ADDRESS if Config.FUNDER_ADDRESS else None
            )
            # Derive API credentials
            self.clob_client.set_api_creds(self.clob_client.create_or_derive_api_creds())
            print("✅ Live Polymarket client initialized")
        except Exception as e:
            print(f"⚠️ Failed to init live client: {e}")
            self.clob_client = None
    
    # ═══════════════════════════════════════════════════════════════════
    # BALANCE & POSITIONS
    # ═══════════════════════════════════════════════════════════════════
    
    async def get_balance(self) -> float:
        """Get USDC balance."""
        if self.is_paper or not self.clob_client:
            return self._paper_balance
        
        try:
            # For live, we need to query the Data API
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/balance",
                    params={"user": Config.FUNDER_ADDRESS}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return float(data.get('balance', 0))
        except Exception as e:
            print(f"⚠️ Balance fetch error: {e}")
        
        return 0.0
    
    async def get_positions(self) -> List[Position]:
        """Get all open positions."""
        if self.is_paper or not self.clob_client:
            return self._get_paper_positions()
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/positions",
                    params={
                        "user": Config.FUNDER_ADDRESS,
                        "sizeThreshold": 0.01
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_positions(data)
        except Exception as e:
            print(f"⚠️ Positions fetch error: {e}")
        
        return []
    
    def _get_paper_positions(self) -> List[Position]:
        """Get paper trading positions."""
        positions = []
        for token_id, pos in self._paper_positions.items():
            pnl = (pos['current_price'] - pos['avg_price']) * pos['size']
            pnl_percent = ((pos['current_price'] / pos['avg_price']) - 1) * 100 if pos['avg_price'] > 0 else 0
            
            positions.append(Position(
                token_id=token_id,
                condition_id=pos.get('condition_id', ''),
                market_question=pos.get('question', 'Unknown Market'),
                outcome=pos.get('outcome', 'Yes'),
                size=pos['size'],
                avg_price=pos['avg_price'],
                current_price=pos['current_price'],
                value=pos['current_price'] * pos['size'],
                pnl=pnl,
                pnl_percent=pnl_percent
            ))
        
        return positions
    
    def _parse_positions(self, data: List[Dict]) -> List[Position]:
        """Parse positions from API response."""
        positions = []
        for item in data:
            try:
                size = float(item.get('size', 0))
                avg_price = float(item.get('avgPrice', 0))
                current_price = float(item.get('currentPrice', avg_price))
                pnl = (current_price - avg_price) * size
                pnl_percent = ((current_price / avg_price) - 1) * 100 if avg_price > 0 else 0
                
                positions.append(Position(
                    token_id=item.get('tokenId', ''),
                    condition_id=item.get('conditionId', ''),
                    market_question=item.get('question', 'Unknown'),
                    outcome=item.get('outcome', 'Yes'),
                    size=size,
                    avg_price=avg_price,
                    current_price=current_price,
                    value=current_price * size,
                    pnl=pnl,
                    pnl_percent=pnl_percent
                ))
            except Exception as e:
                print(f"⚠️ Position parse error: {e}")
        
        return positions
    
    async def get_total_value(self) -> float:
        """Get total portfolio value (balance + positions)."""
        balance = await self.get_balance()
        positions = await self.get_positions()
        position_value = sum(p.value for p in positions)
        return balance + position_value
    
    # ═══════════════════════════════════════════════════════════════════
    # TRADING
    # ═══════════════════════════════════════════════════════════════════
    
    async def buy_market(
        self, 
        token_id: str, 
        amount_usd: float,
        market_info: Optional[Dict] = None
    ) -> OrderResult:
        """
        Execute a market buy order.
        
        Args:
            token_id: The token to buy (yes or no token)
            amount_usd: Dollar amount to spend
            market_info: Optional market details for paper trading
        """
        if amount_usd < Config.MIN_TRADE_USD:
            return OrderResult(success=False, error=f"Min trade: ${Config.MIN_TRADE_USD}")
        
        if amount_usd > Config.MAX_TRADE_USD:
            return OrderResult(success=False, error=f"Max trade: ${Config.MAX_TRADE_USD}")
        
        if self.is_paper or not self.clob_client:
            return await self._paper_buy(token_id, amount_usd, market_info)
        
        try:
            # Live market order
            order = MarketOrderArgs(
                token_id=token_id,
                amount=amount_usd,
                side=BUY,
                order_type=OrderType.FOK  # Fill or Kill for speed
            )
            signed = self.clob_client.create_market_order(order)
            resp = self.clob_client.post_order(signed, OrderType.FOK)
            
            if resp.get('success'):
                return OrderResult(
                    success=True,
                    order_id=resp.get('orderID'),
                    filled_size=float(resp.get('filled', 0)),
                    avg_price=float(resp.get('avgPrice', 0))
                )
            else:
                return OrderResult(success=False, error=resp.get('error', 'Order failed'))
                
        except Exception as e:
            return OrderResult(success=False, error=str(e))
    
    async def _paper_buy(
        self, 
        token_id: str, 
        amount_usd: float,
        market_info: Optional[Dict] = None
    ) -> OrderResult:
        """Execute paper buy order."""
        if amount_usd > self._paper_balance:
            return OrderResult(success=False, error="Insufficient balance")
        
        # Get current price
        price = await self.get_price(token_id)
        if price <= 0:
            price = 0.50  # Default for mock
        
        shares = amount_usd / price
        
        # Add or update position
        if token_id in self._paper_positions:
            pos = self._paper_positions[token_id]
            total_cost = (pos['avg_price'] * pos['size']) + amount_usd
            total_shares = pos['size'] + shares
            pos['avg_price'] = total_cost / total_shares
            pos['size'] = total_shares
            pos['current_price'] = price
        else:
            self._paper_positions[token_id] = {
                'condition_id': market_info.get('condition_id', '') if market_info else '',
                'question': market_info.get('question', 'Paper Trade') if market_info else 'Paper Trade',
                'outcome': market_info.get('outcome', 'Yes') if market_info else 'Yes',
                'size': shares,
                'avg_price': price,
                'current_price': price
            }
        
        self._paper_balance -= amount_usd
        
        return OrderResult(
            success=True,
            order_id=f"paper_{token_id[:8]}_{int(datetime.now().timestamp())}",
            filled_size=shares,
            avg_price=price
        )
    
    async def sell_market(
        self, 
        token_id: str, 
        shares: Optional[float] = None,
        percent: float = 100
    ) -> OrderResult:
        """
        Execute a market sell order.
        
        Args:
            token_id: The token to sell
            shares: Number of shares (if None, uses percent)
            percent: Percentage of position to sell (default 100%)
        """
        if self.is_paper or not self.clob_client:
            return await self._paper_sell(token_id, shares, percent)
        
        try:
            # Get current position size if not specified
            if shares is None:
                positions = await self.get_positions()
                pos = next((p for p in positions if p.token_id == token_id), None)
                if not pos:
                    return OrderResult(success=False, error="Position not found")
                shares = pos.size * (percent / 100)
            
            # Live market sell
            order = MarketOrderArgs(
                token_id=token_id,
                amount=shares,
                side=SELL,
                order_type=OrderType.FOK
            )
            signed = self.clob_client.create_market_order(order)
            resp = self.clob_client.post_order(signed, OrderType.FOK)
            
            if resp.get('success'):
                return OrderResult(
                    success=True,
                    order_id=resp.get('orderID'),
                    filled_size=float(resp.get('filled', 0)),
                    avg_price=float(resp.get('avgPrice', 0))
                )
            else:
                return OrderResult(success=False, error=resp.get('error', 'Order failed'))
                
        except Exception as e:
            return OrderResult(success=False, error=str(e))
    
    async def _paper_sell(
        self, 
        token_id: str,
        shares: Optional[float] = None,
        percent: float = 100
    ) -> OrderResult:
        """Execute paper sell order."""
        if token_id not in self._paper_positions:
            return OrderResult(success=False, error="Position not found")
        
        pos = self._paper_positions[token_id]
        sell_shares = shares if shares else (pos['size'] * percent / 100)
        
        if sell_shares > pos['size']:
            sell_shares = pos['size']
        
        price = pos['current_price']
        proceeds = sell_shares * price
        
        pos['size'] -= sell_shares
        self._paper_balance += proceeds
        
        if pos['size'] <= 0.001:  # Close position
            del self._paper_positions[token_id]
        
        return OrderResult(
            success=True,
            order_id=f"paper_sell_{token_id[:8]}_{int(datetime.now().timestamp())}",
            filled_size=sell_shares,
            avg_price=price
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # MARKET DATA
    # ═══════════════════════════════════════════════════════════════════
    
    async def get_price(self, token_id: str) -> float:
        """Get current price for a token."""
        if self.clob_client:
            try:
                return float(self.clob_client.get_midpoint(token_id))
            except:
                pass
        
        # Fallback to API
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{Config.POLYMARKET_CLOB_URL}/price",
                    params={"token_id": token_id, "side": "buy"}
                )
                if resp.status_code == 200:
                    return float(resp.json().get('price', 0))
        except:
            pass
        
        return 0.0
    
    async def search_markets(
        self, 
        query: str,
        limit: int = 10,
        active_only: bool = True
    ) -> List[Market]:
        """Search for markets by keyword."""
        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "limit": limit,
                    "active": active_only
                }
                if query:
                    params["_q"] = query
                
                resp = await client.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/markets",
                    params=params
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_markets(data)
        except Exception as e:
            print(f"⚠️ Search error: {e}")
        
        return []
    
    async def get_sports_markets(
        self,
        sport: Optional[str] = None,
        limit: int = 20
    ) -> List[Market]:
        """Get sports markets, optionally filtered by sport."""
        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "limit": limit,
                    "active": True,
                    "tag_slug": "sports"
                }
                
                resp = await client.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/markets",
                    params=params
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    markets = self._parse_markets(data)
                    
                    if sport:
                        sport_lower = sport.lower()
                        markets = [m for m in markets if sport_lower in m.question.lower() or sport_lower in m.category.lower()]
                    
                    return markets
        except Exception as e:
            print(f"⚠️ Sports markets error: {e}")
        
        return []
    
    async def get_market_details(self, condition_id: str) -> Optional[Market]:
        """Get detailed info for a specific market."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/markets/{condition_id}"
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    markets = self._parse_markets([data])
                    return markets[0] if markets else None
        except Exception as e:
            print(f"⚠️ Market details error: {e}")
        
        return None
    
    def _parse_markets(self, data: List[Dict]) -> List[Market]:
        """Parse markets from API response."""
        markets = []
        
        for item in data:
            try:
                # Get token prices
                tokens = item.get('tokens', [])
                yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), {})
                no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), {})
                
                markets.append(Market(
                    condition_id=item.get('conditionId', item.get('id', '')),
                    question=item.get('question', 'Unknown'),
                    description=item.get('description', ''),
                    yes_token_id=yes_token.get('token_id', ''),
                    no_token_id=no_token.get('token_id', ''),
                    yes_price=float(yes_token.get('price', 0.5)),
                    no_price=float(no_token.get('price', 0.5)),
                    volume=float(item.get('volume', 0)),
                    category=item.get('category', 'Other'),
                    end_date=item.get('endDate')
                ))
            except Exception as e:
                print(f"⚠️ Market parse error: {e}")
        
        return markets


# Singleton instance
_client: Optional[PolymarketClient] = None

def get_polymarket_client() -> PolymarketClient:
    """Get the Polymarket client singleton."""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client
