"""
Polymarket Client Wrapper

High-level wrapper with EVENTS-based sports market discovery.
Supports sub-markets (toss winner, highest scorer, over/under).
"""

import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
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
    outcome: str
    size: float
    avg_price: float
    current_price: float
    value: float
    pnl: float
    pnl_percent: float


@dataclass
class SubMarket:
    """Represents a sub-market within an event (e.g., toss winner, top scorer)."""
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    group_item_title: str = ""  # e.g., "Toss Winner", "Top Scorer"


@dataclass
class Event:
    """Represents a sports event with multiple sub-markets."""
    event_id: str
    title: str
    description: str
    sport: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    markets: List[SubMarket] = field(default_factory=list)


@dataclass
class Market:
    """Legacy Market class for backward compatibility."""
    condition_id: str
    question: str
    description: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume: float
    category: str
    sport: str = ""
    end_date: Optional[str] = None


@dataclass
class OrderResult:
    """Result of a trade execution."""
    success: bool
    order_id: Optional[str] = None
    filled_size: float = 0.0
    avg_price: float = 0.0
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# SPORT KEYWORDS - for detection and filtering
# ═══════════════════════════════════════════════════════════════════
SPORT_KEYWORDS = {
    'cricket': [
        'cricket', 'ipl', 't20', 'odi', 'test match', 'world cup cricket', 'asia cup',
        'big bash', 'bbl', 'cpl', 'psl', 'hundred', 'bcci',
        'rcb', 'royal challengers', 'csk', 'chennai super kings', 'mumbai indians',
        'kkr', 'kolkata knight riders', 'delhi capitals', 'punjab kings',
        'rajasthan royals', 'sunrisers', 'gujarat titans', 'lucknow',
        'kohli', 'virat', 'rohit sharma', 'dhoni', 'bumrah',
        'innings', 'wicket', 'powerplay', 'sixer'
    ],
    'football': [
        'soccer', 'football', 'premier league', 'epl', 'champions league', 'ucl',
        'la liga', 'bundesliga', 'serie a', 'ligue 1', 'fa cup', 'europa league',
        'manchester united', 'man utd', 'manchester city', 'liverpool',
        'arsenal', 'chelsea', 'tottenham', 'real madrid', 'barcelona',
        'bayern munich', 'juventus', 'psg', 'haaland', 'mbappe', 'salah'
    ],
    'nba': [
        'nba', 'basketball', 'nba playoffs', 'nba finals',
        'lakers', 'celtics', 'warriors', 'nuggets', 'heat', 'bucks',
        'lebron', 'curry', 'durant', 'giannis', 'jokic', 'embiid'
    ],
    'nfl': [
        'nfl', 'american football', 'super bowl', 'nfl playoffs',
        'chiefs', 'bills', 'eagles', 'cowboys', '49ers', 'ravens',
        'mahomes', 'allen', 'hurts', 'lamar jackson'
    ],
    'tennis': [
        'tennis', 'wimbledon', 'us open', 'australian open', 'french open',
        'atp', 'wta', 'djokovic', 'nadal', 'alcaraz', 'sinner', 'swiatek'
    ],
    'ufc': [
        'ufc', 'mma', 'mixed martial arts', 'bellator',
        'jones', 'adesanya', 'makhachev', 'volkanovski', "o'malley"
    ]
}

# Flatten for quick lookup
ALL_SPORT_KEYWORDS = []
for keywords in SPORT_KEYWORDS.values():
    ALL_SPORT_KEYWORDS.extend(keywords)


# ═══════════════════════════════════════════════════════════════════
# SPORT TAG SLUGS - for Gamma API server-side filtering
# These map to the tag_slug parameter in the /events endpoint
# ═══════════════════════════════════════════════════════════════════
SPORT_TAG_SLUGS = {
    'cricket': ['cricket', 'ipl', 't20', 'world-cup-cricket'],
    'football': ['football', 'soccer', 'premier-league', 'champions-league', 'epl'],
    'nba': ['nba', 'basketball'],
    'nfl': ['nfl', 'american-football', 'super-bowl'],
    'tennis': ['tennis', 'wimbledon', 'us-open', 'australian-open'],
    'ufc': ['ufc', 'mma', 'mixed-martial-arts']
}

# Primary search queries for each sport (used with _q parameter)
SPORT_SEARCH_QUERIES = {
    'cricket': ['cricket', 'ipl', 't20'],
    'football': ['football', 'soccer', 'premier league'],
    'nba': ['nba', 'basketball'],
    'nfl': ['nfl', 'super bowl'],
    'tennis': ['tennis', 'wimbledon'],
    'ufc': ['ufc', 'mma']
}


def detect_sport(text: str) -> str:
    """Detect which sport a text belongs to."""
    text_lower = text.lower()
    for sport, keywords in SPORT_KEYWORDS.items():
        if any(keyword in text_lower for keyword in keywords):
            return sport
    return ''


def is_sports_market(question: str, description: str = '') -> bool:
    """Check if a market is sports-related."""
    text = f"{question} {description}".lower()
    return any(keyword in text for keyword in ALL_SPORT_KEYWORDS)


class PolymarketClient:
    """
    Polymarket client with EVENT-based sports market discovery.
    
    Structure:
    - Sports Series (from /sports) 
    - Events (matches within a series)
    - Sub-Markets (toss, highest scorer, winner, over/under)
    """
    
    def __init__(self):
        self.is_paper = Config.is_paper_mode()
        self.clob_client = None
        self._paper_balance = 1000.0
        self._paper_positions: Dict[str, Dict] = {}
        
        if not self.is_paper and CLOB_AVAILABLE and Config.POLYGON_PRIVATE_KEY:
            self._init_live_client()
        else:
            print(f"📝 Paper trading mode")
    
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
            self.clob_client.set_api_creds(self.clob_client.create_or_derive_api_creds())
            print("✅ Live Polymarket client initialized")
        except Exception as e:
            print(f"⚠️ Failed to init live client: {e}")
            self.clob_client = None
    
    async def _fetch_with_retry(
        self, 
        url: str, 
        params: Optional[Dict] = None,
        max_retries: int = 3,
        timeout: int = 30
    ) -> Optional[Dict]:
        """
        Fetch data from URL with exponential backoff retry logic.
        
        Args:
            url: The URL to fetch
            params: Query parameters
            max_retries: Max retry attempts (default 3)
            timeout: Request timeout in seconds
        
        Returns:
            JSON response as dict, or None if all retries failed
        """
        import asyncio
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, params=params)
                    
                    # Success
                    if resp.status_code == 200:
                        return resp.json()
                    
                    # Permanent errors - don't retry
                    if resp.status_code in (400, 404):
                        print(f"⚠️ Permanent error {resp.status_code} for {url}")
                        return None
                    
                    # Rate limiting or server error - retry with backoff
                    if resp.status_code in (429, 500, 502, 503):
                        wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                        print(f"⏳ Got {resp.status_code}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    # Other error codes
                    print(f"⚠️ Unexpected status {resp.status_code} for {url}")
                    return None
                    
            except httpx.TimeoutException:
                wait_time = 2 ** attempt
                print(f"⏳ Timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
                
            except httpx.ConnectError:
                wait_time = 2 ** attempt
                print(f"⏳ Connection error, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                print(f"⚠️ Fetch error: {e}")
                return None
        
        print(f"❌ All {max_retries} retries failed for {url}")
        return None
    
    # ═══════════════════════════════════════════════════════════════════
    # PAPER TRADING PERSISTENCE
    # ═══════════════════════════════════════════════════════════════════
    
    async def _init_paper_db(self):
        """Initialize paper trading database tables."""
        import aiosqlite
        try:
            async with aiosqlite.connect(Config.DATABASE_PATH) as db:
                # Paper positions table
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS paper_positions (
                        token_id TEXT PRIMARY KEY,
                        condition_id TEXT,
                        question TEXT,
                        outcome TEXT,
                        size REAL,
                        avg_price REAL,
                        current_price REAL,
                        updated_at TEXT
                    )
                ''')
                
                # Paper balance table
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS paper_balance (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        balance REAL DEFAULT 1000.0,
                        updated_at TEXT
                    )
                ''')
                
                await db.commit()
        except Exception as e:
            print(f"⚠️ Paper DB init error: {e}")
    
    async def _load_paper_positions(self):
        """Load paper positions from database."""
        import aiosqlite
        from datetime import datetime
        
        try:
            # Initialize tables first
            await self._init_paper_db()
            
            async with aiosqlite.connect(Config.DATABASE_PATH) as db:
                # Load balance
                async with db.execute('SELECT balance FROM paper_balance WHERE id = 1') as cursor:
                    row = await cursor.fetchone()
                    if row:
                        self._paper_balance = float(row[0])
                    else:
                        # Insert default balance
                        await db.execute(
                            'INSERT OR REPLACE INTO paper_balance (id, balance, updated_at) VALUES (1, 1000.0, ?)',
                            (datetime.now().isoformat(),)
                        )
                        await db.commit()
                
                # Load positions
                async with db.execute(
                    'SELECT token_id, condition_id, question, outcome, size, avg_price, current_price FROM paper_positions'
                ) as cursor:
                    rows = await cursor.fetchall()
                    for row in rows:
                        self._paper_positions[row[0]] = {
                            'condition_id': row[1],
                            'question': row[2],
                            'outcome': row[3],
                            'size': row[4],
                            'avg_price': row[5],
                            'current_price': row[6]
                        }
            
            print(f"📂 Loaded {len(self._paper_positions)} paper positions, balance: ${self._paper_balance:.2f}")
        except Exception as e:
            print(f"⚠️ Load paper positions error: {e}")
    
    async def _save_paper_position(self, token_id: str, position: Dict):
        """Save a paper position to database."""
        import aiosqlite
        from datetime import datetime
        
        try:
            async with aiosqlite.connect(Config.DATABASE_PATH) as db:
                await db.execute('''
                    INSERT OR REPLACE INTO paper_positions 
                    (token_id, condition_id, question, outcome, size, avg_price, current_price, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    token_id,
                    position.get('condition_id', ''),
                    position.get('question', 'Paper Trade'),
                    position.get('outcome', 'Yes'),
                    position.get('size', 0),
                    position.get('avg_price', 0),
                    position.get('current_price', 0),
                    datetime.now().isoformat()
                ))
                await db.commit()
        except Exception as e:
            print(f"⚠️ Save paper position error: {e}")
    
    async def _delete_paper_position(self, token_id: str):
        """Delete a paper position from database."""
        import aiosqlite
        
        try:
            async with aiosqlite.connect(Config.DATABASE_PATH) as db:
                await db.execute('DELETE FROM paper_positions WHERE token_id = ?', (token_id,))
                await db.commit()
        except Exception as e:
            print(f"⚠️ Delete paper position error: {e}")
    
    async def _save_paper_balance(self):
        """Save paper balance to database."""
        import aiosqlite
        from datetime import datetime
        
        try:
            async with aiosqlite.connect(Config.DATABASE_PATH) as db:
                await db.execute(
                    'INSERT OR REPLACE INTO paper_balance (id, balance, updated_at) VALUES (1, ?, ?)',
                    (self._paper_balance, datetime.now().isoformat())
                )
                await db.commit()
        except Exception as e:
            print(f"⚠️ Save paper balance error: {e}")
    
    # ═══════════════════════════════════════════════════════════════════
    # BALANCE & POSITIONS
    # ═══════════════════════════════════════════════════════════════════
    
    async def get_balance(self) -> float:
        """Get USDC balance."""
        if self.is_paper or not self.clob_client:
            return self._paper_balance
        
        try:
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
                    params={"user": Config.FUNDER_ADDRESS, "sizeThreshold": 0.01}
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
        """Get total portfolio value."""
        balance = await self.get_balance()
        positions = await self.get_positions()
        position_value = sum(p.value for p in positions)
        return balance + position_value
    
    # ═══════════════════════════════════════════════════════════════════
    # EVENTS & SUB-MARKETS (NEW APPROACH)
    # ═══════════════════════════════════════════════════════════════════
    
    async def get_sports_events(self, sport: str, limit: int = 15) -> List[Event]:
        """
        Fetch sports EVENTS (matches) with their sub-markets.
        
        Uses a 3-tier approach for accurate filtering:
        1. Server-side: Use tag_slug parameter for known sport tags
        2. Server-side fallback: Use _q search query on /markets endpoint
        3. Client-side: Keyword validation as final safety net
        """
        events = []
        seen_ids = set()  # Deduplicate across multiple queries
        sport_lower = sport.lower()
        sport_kws = SPORT_KEYWORDS.get(sport_lower, [sport_lower])
        tag_slugs = SPORT_TAG_SLUGS.get(sport_lower, [sport_lower])
        search_queries = SPORT_SEARCH_QUERIES.get(sport_lower, [sport_lower])
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # ═══════════════════════════════════════════════════════════
                # APPROACH 1: Server-side filtering with tag_slug
                # This is the most reliable method - asks API to filter for us
                # ═══════════════════════════════════════════════════════════
                for tag_slug in tag_slugs:
                    if len(events) >= limit:
                        break
                    
                    params = {
                        "tag_slug": tag_slug,
                        "active": True,
                        "closed": False,
                        "limit": 50
                    }
                    
                    try:
                        resp = await client.get(
                            f"{Config.POLYMARKET_GAMMA_URL}/events",
                            params=params
                        )
                        
                        if resp.status_code == 200:
                            data = resp.json()
                            print(f"📡 tag_slug={tag_slug}: got {len(data)} events")
                            
                            for item in data:
                                event_id = item.get('id', '')
                                if event_id in seen_ids:
                                    continue
                                seen_ids.add(event_id)
                                
                                parsed = self._parse_event(item, sport_lower, sport_kws)
                                if parsed:
                                    events.append(parsed)
                                    if len(events) >= limit:
                                        break
                    except Exception as e:
                        print(f"⚠️ tag_slug {tag_slug} error: {e}")
                        continue
                
                # ═══════════════════════════════════════════════════════════
                # APPROACH 2: Server-side search with _q parameter on /markets
                # Fallback if tag_slug returns insufficient results
                # ═══════════════════════════════════════════════════════════
                if len(events) < limit:
                    for query in search_queries:
                        if len(events) >= limit:
                            break
                        
                        params = {
                            "_q": query,
                            "active": True,
                            "closed": False,
                            "limit": 30
                        }
                        
                        try:
                            resp = await client.get(
                                f"{Config.POLYMARKET_GAMMA_URL}/markets",
                                params=params
                            )
                            
                            if resp.status_code == 200:
                                data = resp.json()
                                print(f"📡 _q={query}: got {len(data)} markets")
                                
                                for item in data:
                                    market_id = item.get('conditionId', item.get('id', ''))
                                    if market_id in seen_ids:
                                        continue
                                    
                                    # Client-side validation - must match sport keywords
                                    question = item.get('question', '')
                                    description = item.get('description', '')
                                    combined = f"{question} {description}".lower()
                                    
                                    if any(kw in combined for kw in sport_kws):
                                        seen_ids.add(market_id)
                                        event = self._market_to_event(item, sport_lower)
                                        if event:
                                            events.append(event)
                                            if len(events) >= limit:
                                                break
                        except Exception as e:
                            print(f"⚠️ _q={query} error: {e}")
                            continue
                
                # ═══════════════════════════════════════════════════════════
                # APPROACH 3: Broad fetch with strict client-side filtering
                # Last resort - only if approaches 1 & 2 return nothing
                # ═══════════════════════════════════════════════════════════
                if not events:
                    print(f"⚠️ No results from server-side filtering, trying broad fetch")
                    params = {
                        "active": True,
                        "closed": False,
                        "limit": 100
                    }
                    
                    resp = await client.get(
                        f"{Config.POLYMARKET_GAMMA_URL}/events",
                        params=params
                    )
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        
                        for item in data:
                            event_id = item.get('id', '')
                            if event_id in seen_ids:
                                continue
                            
                            parsed = self._parse_event(item, sport_lower, sport_kws)
                            if parsed:
                                seen_ids.add(event_id)
                                events.append(parsed)
                                if len(events) >= limit:
                                    break
                    
        except Exception as e:
            print(f"⚠️ Events fetch error: {e}")
        
        print(f"📊 Found {len(events)} {sport} events")
        return events
    
    def _parse_event(self, item: Dict, sport: str, sport_kws: List[str]) -> Optional[Event]:
        """Parse an event from API response with strict keyword validation."""
        title = item.get('title', item.get('question', ''))
        description = item.get('description', '')
        combined = f"{title} {description}".lower()
        
        # STRICT filtering - must match sport keywords
        if not any(kw in combined for kw in sport_kws):
            return None
        
        # Parse sub-markets
        sub_markets = []
        raw_markets = item.get('markets', [])
        
        for m in raw_markets:
            tokens = m.get('tokens', [])
            yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), {})
            no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), {})
            
            # Try to get prices from outcomePrices if tokens don't have them
            yes_price = float(yes_token.get('price', 0.5))
            no_price = float(no_token.get('price', 0.5))
            
            outcome_prices = m.get('outcomePrices')
            if outcome_prices and (yes_price == 0.5 or no_price == 0.5):
                try:
                    import json
                    prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                    if len(prices) >= 2:
                        yes_price = float(prices[0])
                        no_price = float(prices[1])
                except:
                    pass
            
            sub_markets.append(SubMarket(
                condition_id=m.get('conditionId', m.get('id', '')),
                question=m.get('question', m.get('groupItemTitle', 'Unknown')),
                yes_token_id=yes_token.get('token_id', ''),
                no_token_id=no_token.get('token_id', ''),
                yes_price=yes_price,
                no_price=no_price,
                group_item_title=m.get('groupItemTitle', '')
            ))
        
        # If no sub-markets, create one from event itself
        if not sub_markets:
            tokens = item.get('tokens', [])
            yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), {})
            no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), {})
            
            sub_markets.append(SubMarket(
                condition_id=item.get('conditionId', item.get('id', '')),
                question=title,
                yes_token_id=yes_token.get('token_id', ''),
                no_token_id=no_token.get('token_id', ''),
                yes_price=float(yes_token.get('price', 0.5)),
                no_price=float(no_token.get('price', 0.5)),
                group_item_title='Match Winner'
            ))
        
        return Event(
            event_id=item.get('id', ''),
            title=title,
            description=description,
            sport=sport,
            start_date=item.get('startDate'),
            end_date=item.get('endDate'),
            markets=sub_markets
        )
    
    def _market_to_event(self, item: Dict, sport: str) -> Optional[Event]:
        """Convert a market to an Event with a single sub-market."""
        question = item.get('question', '')
        tokens = item.get('tokens', [])
        yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), {})
        no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), {})
        
        # Try outcomePrices if prices are default
        yes_price = float(yes_token.get('price', 0.5))
        no_price = float(no_token.get('price', 0.5))
        
        outcome_prices = item.get('outcomePrices')
        if outcome_prices and (yes_price == 0.5 or no_price == 0.5):
            try:
                import json
                prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                if len(prices) >= 2:
                    yes_price = float(prices[0])
                    no_price = float(prices[1])
            except:
                pass
        
        sub_market = SubMarket(
            condition_id=item.get('conditionId', item.get('id', '')),
            question=question,
            yes_token_id=yes_token.get('token_id', ''),
            no_token_id=no_token.get('token_id', ''),
            yes_price=yes_price,
            no_price=no_price,
            group_item_title='Market'
        )
        
        return Event(
            event_id=item.get('conditionId', item.get('id', '')),
            title=question,
            description=item.get('description', ''),
            sport=sport,
            end_date=item.get('endDate'),
            markets=[sub_market]
        )
    
    async def get_sports_markets(
        self,
        sport: Optional[str] = None,
        limit: int = 20
    ) -> List[Market]:
        """
        Get sports markets with server-side filtering via _q parameter.
        Falls back to alternative keywords if primary returns insufficient results.
        Client-side keyword validation as final safety net.
        """
        all_markets = []
        seen_ids = set()
        sport_lower = sport.lower() if sport else ''
        sport_kws = SPORT_KEYWORDS.get(sport_lower, [sport_lower]) if sport_lower else ALL_SPORT_KEYWORDS
        search_queries = SPORT_SEARCH_QUERIES.get(sport_lower, [sport_lower]) if sport_lower else ['']
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # ═══════════════════════════════════════════════════════════
                # Server-side search with _q parameter
                # ═══════════════════════════════════════════════════════════
                for query in search_queries:
                    if len(all_markets) >= limit:
                        break
                    
                    params = {
                        "limit": 50,
                        "active": True,
                        "closed": False
                    }
                    
                    # Add search query for server-side filtering
                    if query:
                        params["_q"] = query
                    
                    try:
                        resp = await client.get(
                            f"{Config.POLYMARKET_GAMMA_URL}/markets",
                            params=params
                        )
                        
                        if resp.status_code == 200:
                            data = resp.json()
                            print(f"📡 markets _q={query or 'none'}: got {len(data)} results")
                            
                            for item in data:
                                market_id = item.get('conditionId', item.get('id', ''))
                                if market_id in seen_ids:
                                    continue
                                
                                question = item.get('question', '')
                                description = item.get('description', '')
                                combined = f"{question} {description}".lower()
                                
                                # Client-side validation - STRICT filtering
                                if any(kw in combined for kw in sport_kws):
                                    seen_ids.add(market_id)
                                    tokens = item.get('tokens', [])
                                    yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), {})
                                    no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), {})
                                    
                                    # Try outcomePrices if default prices
                                    yes_price = float(yes_token.get('price', 0.5))
                                    no_price = float(no_token.get('price', 0.5))
                                    
                                    outcome_prices = item.get('outcomePrices')
                                    if outcome_prices and (yes_price == 0.5 or no_price == 0.5):
                                        try:
                                            import json
                                            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                                            if len(prices) >= 2:
                                                yes_price = float(prices[0])
                                                no_price = float(prices[1])
                                        except:
                                            pass
                                    
                                    all_markets.append(Market(
                                        condition_id=market_id,
                                        question=question,
                                        description=description,
                                        yes_token_id=yes_token.get('token_id', ''),
                                        no_token_id=no_token.get('token_id', ''),
                                        yes_price=yes_price,
                                        no_price=no_price,
                                        volume=float(item.get('volume', 0)),
                                        category=item.get('category', 'Sports'),
                                        sport=sport_lower or detect_sport(question),
                                        end_date=item.get('endDate')
                                    ))
                                    
                                    if len(all_markets) >= limit:
                                        break
                    except Exception as e:
                        print(f"⚠️ _q={query} error: {e}")
                        continue
                                
        except Exception as e:
            print(f"⚠️ Markets fetch error: {e}")
        
        print(f"📊 Found {len(all_markets)} {sport or 'sports'} markets")
        return all_markets
    
    async def search_markets(
        self, 
        query: str,
        limit: int = 10,
        active_only: bool = True
    ) -> List[Market]:
        """Search for markets by keyword."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                params = {
                    "limit": limit * 2,
                    "active": active_only,
                    "closed": False,
                    "_q": query
                }
                
                resp = await client.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/markets",
                    params=params
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_markets(data)[:limit]
                    
        except Exception as e:
            print(f"⚠️ Search error: {e}")
        
        return []
    
    async def get_market_details(self, condition_id: str) -> Optional[Market]:
        """Get detailed info for a specific market."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
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
                tokens = item.get('tokens', [])
                yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), {})
                no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), {})
                
                question = item.get('question', 'Unknown')
                description = item.get('description', '')
                
                markets.append(Market(
                    condition_id=item.get('conditionId', item.get('id', '')),
                    question=question,
                    description=description,
                    yes_token_id=yes_token.get('token_id', ''),
                    no_token_id=no_token.get('token_id', ''),
                    yes_price=float(yes_token.get('price', 0.5)),
                    no_price=float(no_token.get('price', 0.5)),
                    volume=float(item.get('volume', 0)),
                    category=item.get('category', 'Other'),
                    sport=detect_sport(f"{question} {description}"),
                    end_date=item.get('endDate')
                ))
            except Exception as e:
                print(f"⚠️ Market parse error: {e}")
        
        return markets
    
    # ═══════════════════════════════════════════════════════════════════
    # TRADING
    # ═══════════════════════════════════════════════════════════════════
    
    async def get_price(self, token_id: str, refresh_from_clob: bool = False) -> float:
        """
        Get current price for a token.
        
        Args:
            token_id: The token ID to get price for
            refresh_from_clob: If True, skip any cached values and fetch from CLOB
        
        Returns:
            Price as float (0.0 to 1.0), or 0.0 if unavailable
        """
        # Try py-clob-client midpoint first
        if self.clob_client and not refresh_from_clob:
            try:
                midpoint = self.clob_client.get_midpoint(token_id)
                if midpoint and float(midpoint) > 0:
                    return float(midpoint)
            except:
                pass
        
        # Try CLOB REST API with buy side price
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{Config.POLYMARKET_CLOB_URL}/price",
                    params={"token_id": token_id, "side": "buy"}
                )
                if resp.status_code == 200:
                    price = resp.json().get('price', 0)
                    if price and float(price) > 0:
                        return float(price)
        except Exception as e:
            print(f"⚠️ CLOB price fetch error: {e}")
        
        # Try midpoint endpoint as fallback
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{Config.POLYMARKET_CLOB_URL}/midpoint",
                    params={"token_id": token_id}
                )
                if resp.status_code == 200:
                    mid = resp.json().get('mid', 0)
                    if mid and float(mid) > 0:
                        return float(mid)
        except:
            pass
        
        return 0.0
    
    async def refresh_prices(self, token_ids: List[str]) -> Dict[str, float]:
        """
        Refresh prices for multiple tokens from CLOB.
        Useful when Gamma API returns default 50¢ values.
        
        Args:
            token_ids: List of token IDs to refresh
        
        Returns:
            Dict mapping token_id to current price
        """
        prices = {}
        for token_id in token_ids:
            if token_id:
                price = await self.get_price(token_id, refresh_from_clob=True)
                if price > 0:
                    prices[token_id] = price
        return prices
    
    async def buy_market(
        self, 
        token_id: str, 
        amount_usd: float,
        market_info: Optional[Dict] = None,
        slippage: Optional[float] = None
    ) -> OrderResult:
        """
        Execute a market buy order.
        
        Args:
            token_id: Token to buy
            amount_usd: Amount in USD to spend
            market_info: Optional market metadata
            slippage: Slippage tolerance in percent (e.g., 2.0 = 2%). Uses Config.DEFAULT_SLIPPAGE if None.
        """
        # Apply default slippage if not specified
        if slippage is None:
            slippage = Config.DEFAULT_SLIPPAGE
        
        if amount_usd < Config.MIN_TRADE_USD:
            return OrderResult(success=False, error=f"Min trade: ${Config.MIN_TRADE_USD}")
        
        if amount_usd > Config.MAX_TRADE_USD:
            return OrderResult(success=False, error=f"Max trade: ${Config.MAX_TRADE_USD}")
        
        if self.is_paper or not self.clob_client:
            return await self._paper_buy(token_id, amount_usd, market_info)
        
        try:
            # Get current price for slippage calculation
            current_price = await self.get_price(token_id)
            if current_price <= 0:
                current_price = 0.50  # Fallback
            
            # Calculate max acceptable price with slippage
            max_price = min(current_price * (1 + slippage / 100), 0.99)
            
            # MarketOrderArgs only takes token_id and amount
            order = MarketOrderArgs(
                token_id=token_id,
                amount=amount_usd
            )
            
            # Use the correct method signature - create order then post with FOK
            signed = self.clob_client.create_market_order(order)
            resp = self.clob_client.post_order(signed, OrderType.FOK)
            
            # Handle response - could be dict or object with attributes
            success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
            
            if success:
                order_id = resp.get('orderID', resp.get('order_id', '')) if isinstance(resp, dict) else getattr(resp, 'orderID', getattr(resp, 'order_id', ''))
                filled = resp.get('filled', resp.get('filledSize', 0)) if isinstance(resp, dict) else getattr(resp, 'filled', getattr(resp, 'filledSize', 0))
                avg_price = resp.get('avgPrice', resp.get('average_price', 0)) if isinstance(resp, dict) else getattr(resp, 'avgPrice', getattr(resp, 'average_price', 0))
                
                return OrderResult(
                    success=True,
                    order_id=str(order_id),
                    filled_size=float(filled) if filled else 0,
                    avg_price=float(avg_price) if avg_price else 0
                )
            else:
                error = resp.get('error', resp.get('errorMsg', 'Order failed')) if isinstance(resp, dict) else getattr(resp, 'error', getattr(resp, 'errorMsg', 'Order failed'))
                return OrderResult(success=False, error=str(error))
                
        except Exception as e:
            return OrderResult(success=False, error=str(e))
    
    async def buy_limit(
        self,
        token_id: str,
        price: float,
        size: float,
        expiration: Optional[int] = None
    ) -> OrderResult:
        """
        Place a limit buy order (GTC - Good 'Til Cancelled).
        
        Args:
            token_id: Token to buy
            price: Limit price (0.01 to 0.99)
            size: Number of shares to buy
            expiration: Optional expiration timestamp (seconds since epoch)
        
        Returns:
            OrderResult with order_id for tracking
        """
        if price < 0.01 or price > 0.99:
            return OrderResult(success=False, error="Price must be between 0.01 and 0.99")
        
        if size <= 0:
            return OrderResult(success=False, error="Size must be positive")
        
        cost = price * size
        if cost < Config.MIN_TRADE_USD:
            return OrderResult(success=False, error=f"Min trade value: ${Config.MIN_TRADE_USD}")
        
        if self.is_paper or not self.clob_client:
            return await self._paper_limit_order(token_id, price, size, 'buy')
        
        try:
            # Create limit order using OrderArgs
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=BUY
            )
            
            signed = self.clob_client.create_order(order_args)
            
            # Post as GTC (Good 'Til Cancelled)
            resp = self.clob_client.post_order(signed, OrderType.GTC)
            
            success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
            
            if success:
                order_id = resp.get('orderID', resp.get('order_id', '')) if isinstance(resp, dict) else getattr(resp, 'orderID', getattr(resp, 'order_id', ''))
                return OrderResult(
                    success=True,
                    order_id=str(order_id),
                    filled_size=0,  # Limit orders don't fill immediately
                    avg_price=price
                )
            else:
                error = resp.get('error', 'Limit order failed') if isinstance(resp, dict) else getattr(resp, 'error', 'Limit order failed')
                return OrderResult(success=False, error=str(error))
                
        except Exception as e:
            return OrderResult(success=False, error=str(e))
    
    async def sell_limit(
        self,
        token_id: str,
        price: float,
        size: float,
        expiration: Optional[int] = None
    ) -> OrderResult:
        """
        Place a limit sell order (GTC - Good 'Til Cancelled).
        
        Args:
            token_id: Token to sell
            price: Limit price (0.01 to 0.99)
            size: Number of shares to sell
            expiration: Optional expiration timestamp
        
        Returns:
            OrderResult with order_id for tracking
        """
        if price < 0.01 or price > 0.99:
            return OrderResult(success=False, error="Price must be between 0.01 and 0.99")
        
        if size <= 0:
            return OrderResult(success=False, error="Size must be positive")
        
        if self.is_paper or not self.clob_client:
            return await self._paper_limit_order(token_id, price, size, 'sell')
        
        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=SELL
            )
            
            signed = self.clob_client.create_order(order_args)
            resp = self.clob_client.post_order(signed, OrderType.GTC)
            
            success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
            
            if success:
                order_id = resp.get('orderID', resp.get('order_id', '')) if isinstance(resp, dict) else getattr(resp, 'orderID', getattr(resp, 'order_id', ''))
                return OrderResult(
                    success=True,
                    order_id=str(order_id),
                    filled_size=0,
                    avg_price=price
                )
            else:
                error = resp.get('error', 'Limit order failed') if isinstance(resp, dict) else getattr(resp, 'error', 'Limit order failed')
                return OrderResult(success=False, error=str(error))
                
        except Exception as e:
            return OrderResult(success=False, error=str(e))
    
    async def _paper_limit_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str
    ) -> OrderResult:
        """Simulate limit order in paper mode."""
        order_id = f"paper_limit_{side}_{token_id[:8]}_{int(datetime.now().timestamp())}"
        
        # In paper mode, we just record the order
        # A real implementation would check if price crosses and fill
        return OrderResult(
            success=True,
            order_id=order_id,
            filled_size=0,
            avg_price=price
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # ORDER BOOK & OPEN ORDERS
    # ═══════════════════════════════════════════════════════════════════
    
    async def get_order_book(self, token_id: str, depth: int = 10) -> Dict[str, Any]:
        """
        Get order book for a token.
        
        Args:
            token_id: Token to get order book for
            depth: Number of price levels to fetch (default 10)
        
        Returns:
            Dict with 'bids' and 'asks' lists, each containing [price, size] pairs
        """
        try:
            if self.clob_client:
                # Use py-clob-client's get_order_book
                params = BookParams(token_id=token_id)
                book = self.clob_client.get_order_book(params)
                
                # Parse response
                bids = []
                asks = []
                
                if isinstance(book, dict):
                    raw_bids = book.get('bids', [])
                    raw_asks = book.get('asks', [])
                else:
                    raw_bids = getattr(book, 'bids', [])
                    raw_asks = getattr(book, 'asks', [])
                
                for bid in raw_bids[:depth]:
                    price = bid.get('price', bid[0]) if isinstance(bid, dict) else bid[0]
                    size = bid.get('size', bid[1]) if isinstance(bid, dict) else bid[1]
                    bids.append({'price': float(price), 'size': float(size)})
                
                for ask in raw_asks[:depth]:
                    price = ask.get('price', ask[0]) if isinstance(ask, dict) else ask[0]
                    size = ask.get('size', ask[1]) if isinstance(ask, dict) else ask[1]
                    asks.append({'price': float(price), 'size': float(size)})
                
                return {
                    'bids': sorted(bids, key=lambda x: x['price'], reverse=True),
                    'asks': sorted(asks, key=lambda x: x['price']),
                    'spread': asks[0]['price'] - bids[0]['price'] if bids and asks else 0
                }
            
            # Fallback to REST API
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{Config.POLYMARKET_CLOB_URL}/book",
                    params={"token_id": token_id}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        'bids': data.get('bids', [])[:depth],
                        'asks': data.get('asks', [])[:depth],
                        'spread': 0
                    }
                    
        except Exception as e:
            print(f"⚠️ Order book fetch error: {e}")
        
        return {'bids': [], 'asks': [], 'spread': 0}
    
    async def get_open_orders(self, market_id: Optional[str] = None) -> List[Dict]:
        """
        Get all open orders for the user.
        
        Args:
            market_id: Optional filter by market (condition_id)
        
        Returns:
            List of open orders with order_id, token_id, side, price, size, status
        """
        if self.is_paper or not self.clob_client:
            # Paper mode - no persistent open orders
            return []
        
        try:
            params = OpenOrderParams()
            if market_id:
                params.market = market_id
            
            orders = self.clob_client.get_orders(params)
            
            result = []
            for order in orders if orders else []:
                if isinstance(order, dict):
                    result.append({
                        'order_id': order.get('id', order.get('orderID', '')),
                        'token_id': order.get('asset_id', order.get('token_id', '')),
                        'side': order.get('side', 'buy'),
                        'price': float(order.get('price', 0)),
                        'size': float(order.get('original_size', order.get('size', 0))),
                        'filled': float(order.get('size_matched', 0)),
                        'status': order.get('status', 'open'),
                        'created_at': order.get('created_at', '')
                    })
                else:
                    result.append({
                        'order_id': getattr(order, 'id', getattr(order, 'orderID', '')),
                        'token_id': getattr(order, 'asset_id', getattr(order, 'token_id', '')),
                        'side': getattr(order, 'side', 'buy'),
                        'price': float(getattr(order, 'price', 0)),
                        'size': float(getattr(order, 'original_size', getattr(order, 'size', 0))),
                        'filled': float(getattr(order, 'size_matched', 0)),
                        'status': getattr(order, 'status', 'open'),
                        'created_at': getattr(order, 'created_at', '')
                    })
            
            return result
            
        except Exception as e:
            print(f"⚠️ Open orders fetch error: {e}")
            return []
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a specific open order.
        
        Args:
            order_id: The order ID to cancel
        
        Returns:
            True if successful, False otherwise
        """
        if self.is_paper or not self.clob_client:
            return True  # Paper mode - always succeeds
        
        try:
            resp = self.clob_client.cancel(order_id)
            
            if isinstance(resp, dict):
                return resp.get('canceled', False) or resp.get('success', False)
            return getattr(resp, 'canceled', False) or getattr(resp, 'success', False)
            
        except Exception as e:
            print(f"⚠️ Cancel order error: {e}")
            return False
    
    async def cancel_all_orders(self, market_id: Optional[str] = None) -> int:
        """
        Cancel all open orders.
        
        Args:
            market_id: Optional filter by market
        
        Returns:
            Number of orders cancelled
        """
        if self.is_paper or not self.clob_client:
            return 0
        
        try:
            if market_id:
                resp = self.clob_client.cancel_market_orders(market_id)
            else:
                resp = self.clob_client.cancel_all()
            
            if isinstance(resp, dict):
                return len(resp.get('canceled', []))
            return len(getattr(resp, 'canceled', []))
            
        except Exception as e:
            print(f"⚠️ Cancel all orders error: {e}")
            return 0
    
    async def _paper_buy(
        self, 
        token_id: str, 
        amount_usd: float,
        market_info: Optional[Dict] = None
    ) -> OrderResult:
        """Execute paper buy order."""
        if amount_usd > self._paper_balance:
            return OrderResult(success=False, error="Insufficient balance")
        
        price = await self.get_price(token_id)
        if price <= 0:
            price = 0.50
        
        shares = amount_usd / price
        
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
        
        # Persist position and balance to database
        await self._save_paper_position(token_id, self._paper_positions[token_id])
        await self._save_paper_balance()
        
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
        """Execute a market sell order."""
        if self.is_paper or not self.clob_client:
            return await self._paper_sell(token_id, shares, percent)
        
        try:
            if shares is None:
                positions = await self.get_positions()
                pos = next((p for p in positions if p.token_id == token_id), None)
                if not pos:
                    return OrderResult(success=False, error="Position not found")
                shares = pos.size * (percent / 100)
            
            # MarketOrderArgs only takes token_id and amount
            # For sells, we pass the number of shares to sell
            order = MarketOrderArgs(
                token_id=token_id,
                amount=shares
            )
            
            # Create and post the sell order
            signed = self.clob_client.create_market_order(order)
            resp = self.clob_client.post_order(signed, OrderType.FOK)
            
            # Handle response - could be dict or object with attributes
            success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
            
            if success:
                order_id = resp.get('orderID', resp.get('order_id', '')) if isinstance(resp, dict) else getattr(resp, 'orderID', getattr(resp, 'order_id', ''))
                filled = resp.get('filled', resp.get('filledSize', 0)) if isinstance(resp, dict) else getattr(resp, 'filled', getattr(resp, 'filledSize', 0))
                avg_price = resp.get('avgPrice', resp.get('average_price', 0)) if isinstance(resp, dict) else getattr(resp, 'avgPrice', getattr(resp, 'average_price', 0))
                
                return OrderResult(
                    success=True,
                    order_id=str(order_id),
                    filled_size=float(filled) if filled else 0,
                    avg_price=float(avg_price) if avg_price else 0
                )
            else:
                error = resp.get('error', resp.get('errorMsg', 'Order failed')) if isinstance(resp, dict) else getattr(resp, 'error', getattr(resp, 'errorMsg', 'Order failed'))
                return OrderResult(success=False, error=str(error))
                
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
        
        if pos['size'] <= 0.001:
            del self._paper_positions[token_id]
            await self._delete_paper_position(token_id)
        else:
            await self._save_paper_position(token_id, pos)
        
        # Save updated balance
        await self._save_paper_balance()
        
        return OrderResult(
            success=True,
            order_id=f"paper_sell_{token_id[:8]}_{int(datetime.now().timestamp())}",
            filled_size=sell_shares,
            avg_price=price
        )
    
    async def async_init(self):
        """
        Async initialization - load paper positions from database.
        Call this after creating the client to restore persisted state.
        """
        if self.is_paper:
            await self._load_paper_positions()


# Singleton instance
_client: Optional[PolymarketClient] = None
_initialized: bool = False

def get_polymarket_client() -> PolymarketClient:
    """Get the Polymarket client singleton."""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client

async def init_polymarket_client() -> PolymarketClient:
    """
    Initialize the Polymarket client asynchronously.
    Call this on bot startup to load persisted paper positions.
    """
    global _client, _initialized
    if _client is None:
        _client = PolymarketClient()
    if not _initialized:
        await _client.async_init()
        _initialized = True
    return _client
