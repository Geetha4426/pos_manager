"""
Favorites Database

SQLite-based storage for saved favorite markets.
"""

import aiosqlite
import os
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


@dataclass
class Favorite:
    """A favorited market."""
    id: int
    user_id: str
    market_id: str  # condition_id
    token_id: str
    label: str
    outcome: str  # "Yes" or "No"
    created_at: str


class FavoritesDB:
    """SQLite database for favorites."""
    
    def __init__(self):
        self.db_path = Config.DATABASE_PATH
        self._ensure_dir()
    
    def _ensure_dir(self):
        """Ensure database directory exists."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
    
    async def init_db(self):
        """Initialize the database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    market_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    outcome TEXT DEFAULT 'Yes',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, market_id, outcome)
                )
            ''')
            await db.commit()
    
    async def add_favorite(
        self,
        user_id: str,
        market_id: str,
        token_id: str,
        label: str,
        outcome: str = "Yes"
    ) -> bool:
        """Add a market to favorites."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT OR REPLACE INTO favorites 
                       (user_id, market_id, token_id, label, outcome, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (user_id, market_id, token_id, label, outcome, datetime.now().isoformat())
                )
                await db.commit()
            return True
        except Exception as e:
            print(f"⚠️ Add favorite error: {e}")
            return False
    
    async def remove_favorite(self, user_id: str, market_id: str, outcome: str = None) -> bool:
        """Remove a market from favorites."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                if outcome:
                    await db.execute(
                        'DELETE FROM favorites WHERE user_id = ? AND market_id = ? AND outcome = ?',
                        (user_id, market_id, outcome)
                    )
                else:
                    await db.execute(
                        'DELETE FROM favorites WHERE user_id = ? AND market_id = ?',
                        (user_id, market_id)
                    )
                await db.commit()
            return True
        except Exception as e:
            print(f"⚠️ Remove favorite error: {e}")
            return False
    
    async def get_favorites(self, user_id: str) -> List[Favorite]:
        """Get all favorites for a user."""
        favorites = []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    'SELECT * FROM favorites WHERE user_id = ? ORDER BY created_at DESC',
                    (user_id,)
                ) as cursor:
                    async for row in cursor:
                        favorites.append(Favorite(
                            id=row['id'],
                            user_id=row['user_id'],
                            market_id=row['market_id'],
                            token_id=row['token_id'],
                            label=row['label'],
                            outcome=row['outcome'],
                            created_at=row['created_at']
                        ))
        except Exception as e:
            print(f"⚠️ Get favorites error: {e}")
        
        return favorites
    
    async def is_favorite(self, user_id: str, market_id: str) -> bool:
        """Check if a market is favorited."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    'SELECT 1 FROM favorites WHERE user_id = ? AND market_id = ? LIMIT 1',
                    (user_id, market_id)
                ) as cursor:
                    return await cursor.fetchone() is not None
        except:
            return False


# Singleton instance
_db: Optional[FavoritesDB] = None

async def get_favorites_db() -> FavoritesDB:
    """Get the favorites database singleton."""
    global _db
    if _db is None:
        _db = FavoritesDB()
        await _db.init_db()
    return _db
