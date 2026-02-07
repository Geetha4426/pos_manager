"""
Alert Manager

SQLite-backed storage and management for price alerts, stop-loss, and take-profit orders.
"""

import aiosqlite
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict
from enum import Enum

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


class AlertType(Enum):
    PRICE_ALERT = "price_alert"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


@dataclass
class Alert:
    """Represents a price alert or auto-trade trigger."""
    id: int
    user_id: str
    token_id: str
    market_question: str
    alert_type: AlertType
    trigger_price: float
    current_price: float
    side: str  # 'above' or 'below'
    auto_trade: bool  # If True, execute trade when triggered
    trade_amount: Optional[float]
    created_at: str
    triggered: bool = False


class AlertManager:
    """Manages price alerts and auto-trade triggers."""
    
    def __init__(self):
        self.db_path = Config.DATABASE_PATH
        self._callbacks = []  # List of (callback, bot) tuples for notifications
    
    async def init_db(self):
        """Initialize alerts database table."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    market_question TEXT,
                    alert_type TEXT NOT NULL,
                    trigger_price REAL NOT NULL,
                    side TEXT NOT NULL,
                    auto_trade INTEGER DEFAULT 0,
                    trade_amount REAL,
                    created_at TEXT NOT NULL,
                    triggered INTEGER DEFAULT 0
                )
            ''')
            await db.commit()
    
    async def add_alert(
        self,
        user_id: str,
        token_id: str,
        market_question: str,
        alert_type: AlertType,
        trigger_price: float,
        side: str = "above",
        auto_trade: bool = False,
        trade_amount: Optional[float] = None
    ) -> int:
        """
        Add a new price alert.
        
        Args:
            user_id: Telegram user ID
            token_id: Token to monitor
            market_question: Market title for display
            alert_type: Type of alert (price_alert, stop_loss, take_profit)
            trigger_price: Price threshold (0.01 to 0.99)
            side: 'above' or 'below' - trigger when price crosses this direction
            auto_trade: If True, automatically execute trade when triggered
            trade_amount: Amount to trade if auto_trade is True
        
        Returns:
            Alert ID
        """
        await self.init_db()
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                INSERT INTO alerts 
                (user_id, token_id, market_question, alert_type, trigger_price, side, auto_trade, trade_amount, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                token_id,
                market_question,
                alert_type.value,
                trigger_price,
                side,
                1 if auto_trade else 0,
                trade_amount,
                datetime.now().isoformat()
            ))
            await db.commit()
            return cursor.lastrowid
    
    async def get_alerts(self, user_id: Optional[str] = None, active_only: bool = True) -> List[Alert]:
        """Get all alerts, optionally filtered by user."""
        await self.init_db()
        
        async with aiosqlite.connect(self.db_path) as db:
            query = 'SELECT id, user_id, token_id, market_question, alert_type, trigger_price, side, auto_trade, trade_amount, created_at, triggered FROM alerts'
            params = []
            
            conditions = []
            if user_id:
                conditions.append('user_id = ?')
                params.append(user_id)
            if active_only:
                conditions.append('triggered = 0')
            
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [
                    Alert(
                        id=row[0],
                        user_id=row[1],
                        token_id=row[2],
                        market_question=row[3],
                        alert_type=AlertType(row[4]),
                        trigger_price=row[5],
                        current_price=0,  # Will be filled by price monitor
                        side=row[6],
                        auto_trade=bool(row[7]),
                        trade_amount=row[8],
                        created_at=row[9],
                        triggered=bool(row[10])
                    )
                    for row in rows
                ]
    
    async def remove_alert(self, alert_id: int) -> bool:
        """Remove an alert by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM alerts WHERE id = ?', (alert_id,))
            await db.commit()
            return True
    
    async def mark_triggered(self, alert_id: int):
        """Mark an alert as triggered."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE alerts SET triggered = 1 WHERE id = ?', (alert_id,))
            await db.commit()
    
    async def add_stop_loss(
        self,
        user_id: str,
        token_id: str,
        market_question: str,
        stop_price: float,
        sell_amount: Optional[float] = None
    ) -> int:
        """Add a stop-loss order (sells when price drops below threshold)."""
        return await self.add_alert(
            user_id=user_id,
            token_id=token_id,
            market_question=market_question,
            alert_type=AlertType.STOP_LOSS,
            trigger_price=stop_price,
            side="below",
            auto_trade=True,
            trade_amount=sell_amount
        )
    
    async def add_take_profit(
        self,
        user_id: str,
        token_id: str,
        market_question: str,
        target_price: float,
        sell_amount: Optional[float] = None
    ) -> int:
        """Add a take-profit order (sells when price rises above threshold)."""
        return await self.add_alert(
            user_id=user_id,
            token_id=token_id,
            market_question=market_question,
            alert_type=AlertType.TAKE_PROFIT,
            trigger_price=target_price,
            side="above",
            auto_trade=True,
            trade_amount=sell_amount
        )


# Singleton instance
_alert_manager: Optional[AlertManager] = None

def get_alert_manager() -> AlertManager:
    """Get the AlertManager singleton."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
