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
import json

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
    outcome_yes: str = "Yes"    # Actual label: "Yes" or team name like "India"
    outcome_no: str = "No"      # Actual label: "No" or team name like "Pakistan"


@dataclass
class League:
    """Represents a sports league/series (e.g., IPL, EPL, NBA)."""
    series_id: str
    name: str
    sport: str
    slug: str = ""
    image: str = ""
    event_count: int = 0


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
    outcome_yes: str = "Yes"    # Actual label: "Yes" or team name like "India"
    outcome_no: str = "No"      # Actual label: "No" or team name like "Pakistan"


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
    ],
    'baseball': [
        'mlb', 'baseball', 'world series', 'mlb playoffs',
        'yankees', 'dodgers', 'astros', 'braves', 'phillies', 'mets'
    ],
    'hockey': [
        'nhl', 'hockey', 'stanley cup', 'nhl playoffs',
        'rangers', 'oilers', 'panthers', 'bruins', 'maple leafs'
    ],
    'f1': [
        'formula 1', 'f1', 'grand prix', 'gp', 'motorsport',
        'verstappen', 'hamilton', 'leclerc', 'norris', 'red bull racing'
    ],
    'golf': [
        'golf', 'pga', 'masters', 'ryder cup', 'the open', 'us open golf',
        'scottie scheffler', 'rory mcilroy', 'pga tour'
    ]
}

# Flatten for quick lookup
ALL_SPORT_KEYWORDS = []
for keywords in SPORT_KEYWORDS.values():
    ALL_SPORT_KEYWORDS.extend(keywords)


# ═══════════════════════════════════════════════════════════════════
# SPORT TAG SLUGS - for Gamma API server-side filtering
# These map to the tag_slug parameter in the /events endpoint
# Sourced from Polymarket website categories + Gamma API /tags
# ═══════════════════════════════════════════════════════════════════
SPORT_TAG_SLUGS = {
    'cricket': [
        'cricket', 'ipl', 't20', 'world-cup-cricket', 'odi',
        'test-cricket', 'big-bash', 'bbl', 'psl', 'cpl',
        'the-hundred', 'asia-cup', 'india-cricket',
    ],
    'football': [
        'football', 'soccer', 'premier-league', 'epl',
        'champions-league', 'ucl', 'europa-league',
        'la-liga', 'bundesliga', 'serie-a', 'ligue-1',
        'fa-cup', 'mls', 'copa-america', 'world-cup',
        'euro', 'carabao-cup', 'club-world-cup',
    ],
    'nba': [
        'nba', 'basketball', 'nba-finals', 'nba-playoffs',
        'nba-mvp', 'nba-draft', 'wnba', 'ncaa-basketball',
        'march-madness',
    ],
    'nfl': [
        'nfl', 'american-football', 'super-bowl', 'nfl-playoffs',
        'nfl-draft', 'nfl-mvp', 'college-football',
    ],
    'tennis': [
        'tennis', 'wimbledon', 'us-open', 'australian-open',
        'french-open', 'roland-garros', 'atp', 'wta',
        'atp-finals', 'davis-cup',
    ],
    'ufc': [
        'ufc', 'mma', 'mixed-martial-arts', 'bellator',
        'boxing', 'fight',
    ],
    'baseball': [
        'mlb', 'baseball', 'world-series',
    ],
    'hockey': [
        'nhl', 'hockey', 'stanley-cup',
    ],
    'f1': [
        'formula-1', 'f1', 'grand-prix', 'motorsport',
    ],
    'golf': [
        'golf', 'pga', 'masters', 'ryder-cup', 'the-open',
    ],
}

# Primary search queries for each sport (used with _q parameter)
SPORT_SEARCH_QUERIES = {
    'cricket': ['cricket', 'ipl', 't20', 'odi', 'test match'],
    'football': ['football', 'soccer', 'premier league', 'champions league', 'la liga'],
    'nba': ['nba', 'basketball', 'nba finals'],
    'nfl': ['nfl', 'super bowl', 'american football'],
    'tennis': ['tennis', 'wimbledon', 'us open', 'french open'],
    'ufc': ['ufc', 'mma', 'boxing'],
    'baseball': ['mlb', 'baseball', 'world series'],
    'hockey': ['nhl', 'hockey', 'stanley cup'],
    'f1': ['formula 1', 'f1', 'grand prix'],
    'golf': ['golf', 'pga', 'masters'],
}

# ═══════════════════════════════════════════════════════════════════
# EVENT CATEGORY LABELS - for grouping sub-markets by type
# Maps groupItemTitle patterns to a display category
# ═══════════════════════════════════════════════════════════════════
EVENT_CATEGORIES = {
    'finals': ['final', 'finals', 'championship', 'title'],
    'match': ['match', 'winner', 'game', 'vs', 'versus'],
    'player': ['top scorer', 'mvp', 'man of the match', 'highest', 'most'],
    'series': ['series', 'over/under', 'total', 'spread'],
    'prop': ['prop', 'special', 'bonus', 'first'],
}


# ═══════════════════════════════════════════════════════════════════
# DATE / TIME HELPERS
# ═══════════════════════════════════════════════════════════════════

def parse_event_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 date string from Gamma API into datetime."""
    if not date_str:
        return None
    try:
        # Gamma API returns ISO format like "2025-06-15T14:00:00Z"
        clean = date_str.replace('Z', '+00:00')
        return datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        pass
    # Fallback: try common formats
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S.%f'):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def event_status(start_date: Optional[str], end_date: Optional[str]) -> str:
    """
    Determine event timing status.
    Returns: 'live', 'upcoming', or 'past'
    """
    now = datetime.utcnow()
    start = parse_event_date(start_date)
    end = parse_event_date(end_date)

    if end and end.replace(tzinfo=None) < now:
        return 'past'
    if start and start.replace(tzinfo=None) <= now:
        return 'live'
    return 'upcoming'


def event_sort_key(ev: 'Event'):
    """
    Sort key for events: live first (by start asc), then upcoming (by start asc).
    Past events are pushed to the end.
    """
    status = event_status(ev.start_date, ev.end_date)
    start = parse_event_date(ev.start_date)
    # epoch-far-future fallback so None dates sort last
    ts = start.timestamp() if start else 9999999999
    order = {'live': 0, 'upcoming': 1, 'past': 2}
    return (order.get(status, 2), ts)


def categorize_sub_market(group_item_title: str) -> str:
    """Return a category label for a sub-market based on its groupItemTitle."""
    title_lower = (group_item_title or '').lower()
    for category, keywords in EVENT_CATEGORIES.items():
        if any(kw in title_lower for kw in keywords):
            return category
    return 'other'


def filter_and_sort_events(events: List['Event'], include_past: bool = False) -> List['Event']:
    """
    Filter out past events and sort by: live first → upcoming by date.

    Args:
        events: Raw list of Event objects
        include_past: If True, keep past events at the end (default False)

    Returns:
        Sorted list of non-past events (unless include_past=True)
    """
    if not include_past:
        events = [e for e in events if event_status(e.start_date, e.end_date) != 'past']
    return sorted(events, key=event_sort_key)


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


# Geo-block: Polymarket restricts trading from these countries/regions.
# CLOB API returns 403/451 when accessed from a blocked IP.
GEO_BLOCKED_REGIONS = [
    'United States', 'Cuba', 'Iran', 'North Korea', 'Syria',
    'Russia', 'Belarus', 'Myanmar', 'Venezuela', 'Zimbabwe', 'France'
]
GEO_BLOCK_MSG = (
    "🚫 Polymarket trading is geo-restricted.\n"
    "Your server IP appears to be in a blocked region.\n\n"
    "Blocked regions: US, Cuba, Iran, North Korea, Syria, "
    "Russia, Belarus, Myanmar, Venezuela, Zimbabwe, France.\n\n"
    "💡 Deploy your bot on a server in an allowed region "
    "(e.g., Singapore, UK, Germany, Japan)."
)


def is_geo_block_error(error_msg: str) -> bool:
    """Detect if an error is specifically caused by Polymarket geo-blocking.
    
    IMPORTANT: Only match explicit geo-block keywords.
    Do NOT match generic 'forbidden'/'403' - those are often auth/session errors.
    """
    lower = error_msg.lower()
    return any(kw in lower for kw in (
        'geograph', 'geofence', 'geo restrict', 'geo block', 'geo-block',
        'not available in your region', 'region restriction',
        'unavailable for legal', 'country restriction',
    ))


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
        self._funder_address = ''
        self._geo_block_count = 0  # Track consecutive geo-blocks (not sticky)
        self._consecutive_errors = 0  # Track consecutive CLOB errors
        
        if not self.is_paper and CLOB_AVAILABLE and Config.POLYGON_PRIVATE_KEY:
            self._init_live_client()
        else:
            print(f"📝 Paper trading mode")
    
    def _init_live_client(self):
        """Initialize live trading client.
        
        If CLOB_RELAY_URL is set, routes all CLOB API calls through the relay
        to bypass geo-blocking. Orders are signed locally (private key never
        leaves your machine), only the signed request is forwarded.
        """
        import time as _time
        try:
            t0 = _time.time()
            
            # Funder = Polymarket proxy wallet address (holds your USDC/positions)
            # If not set, ClobClient defaults to signer (EOA) address
            funder = Config.FUNDER_ADDRESS
            if not funder or funder == 'your_funder_address_here':
                funder = None  # Let ClobClient default to signer address
            
            # Use relay URL if configured (bypasses geo-blocking)
            clob_url = Config.get_clob_url()
            if Config.is_relay_enabled():
                print(f"   🔀 Using CLOB relay: {clob_url}")
            
            self.clob_client = ClobClient(
                clob_url,
                key=Config.POLYGON_PRIVATE_KEY,
                chain_id=Config.POLYGON_CHAIN_ID,
                signature_type=Config.SIGNATURE_TYPE,
                funder=funder
            )
            
            # If relay has auth token, patch the session to include it
            if Config.is_relay_enabled() and Config.CLOB_RELAY_AUTH_TOKEN:
                self._patch_clob_session_auth()
            
            print(f"   ↳ ClobClient created ({_time.time()-t0:.1f}s)")
            
            t1 = _time.time()
            self.clob_client.set_api_creds(self.clob_client.create_or_derive_api_creds())
            print(f"   ↳ API creds derived ({_time.time()-t1:.1f}s)")
            
            # Log the funder address being used (for positions/balance queries)
            actual_funder = funder or self.clob_client.get_address()
            self._funder_address = actual_funder
            print(f"   ↳ Funder (proxy wallet): {actual_funder}")
            print(f"   ↳ Signature type: {Config.SIGNATURE_TYPE} ({'EOA' if Config.SIGNATURE_TYPE == 0 else 'Proxy/Magic' if Config.SIGNATURE_TYPE == 1 else 'Proxy'})")
            print(f"   ↳ Signer (EOA): {self.clob_client.get_address()}")
            via = " via relay" if Config.is_relay_enabled() else ""
            print(f"✅ Live Polymarket client initialized{via} ({_time.time()-t0:.1f}s total)")
        except Exception as e:
            print(f"⚠️ Failed to init live client: {e}")
            if is_geo_block_error(str(e)):
                print(GEO_BLOCK_MSG)
                if not Config.is_relay_enabled():
                    print("\n💡 TIP: Set CLOB_RELAY_URL to bypass geo-blocking.")
                    print("   See relay/ folder for Cloudflare Worker setup.\n")
            self.clob_client = None
    
    def _patch_clob_session_auth(self):
        """Inject relay auth token into the ClobClient's HTTP session.
        
        The py-clob-client uses a requests.Session internally.
        We add an Authorization header so the relay can verify requests.
        """
        try:
            # py-clob-client stores session in self.clob_client.session or similar
            session = getattr(self.clob_client, 'session', None)
            if session is None:
                # Try accessing through the http helper
                http = getattr(self.clob_client, 'http', None)
                if http:
                    session = getattr(http, 'session', None)
            
            if session and hasattr(session, 'headers'):
                session.headers['Authorization'] = f'Bearer {Config.CLOB_RELAY_AUTH_TOKEN}'
                print(f"   ↳ Relay auth token injected")
            else:
                print(f"   ⚠️ Could not inject relay auth token (session not found)")
        except Exception as e:
            print(f"   ⚠️ Relay auth injection failed: {e}")
    
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
                    
                    # 403/451 handling (Gamma API is read-only, rarely geo-blocked)
                    if resp.status_code in (403, 451):
                        body = ''
                        try:
                            body = resp.text[:200]
                        except:
                            pass
                        if resp.status_code == 451 or is_geo_block_error(body):
                            print(f"🚫 Geo-blocked ({resp.status_code}): {body}")
                        else:
                            print(f"⚠️ Forbidden {resp.status_code} for {url}: {body}")
                        return None
                    
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
            # Auto-create data directory if it doesn't exist
            db_dir = os.path.dirname(Config.DATABASE_PATH)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                print(f"📁 Created data directory: {db_dir}")
            
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
    
    def _refresh_session(self):
        """Re-derive API credentials if session expired."""
        try:
            if self.clob_client:
                self.clob_client.set_api_creds(
                    self.clob_client.create_or_derive_api_creds()
                )
                print("🔄 CLOB API session refreshed")
        except Exception as e:
            print(f"⚠️ Session refresh failed: {e}")
    
    def _clob_call(self, method, *args, **kwargs):
        """Call a CLOB client method with smart retry and NO sticky lockout.
        
        Strategy:
        - On success: reset error counter
        - On auth/403 errors: refresh session and retry once
        - On explicit geo-block (451 or geo keywords): raise with message
        - On other errors: propagate as-is (never lock out the entire bot)
        """
        try:
            result = method(*args, **kwargs)
            self._consecutive_errors = 0  # Success resets counter
            return result
        except Exception as e:
            self._consecutive_errors += 1
            err_msg = str(e)
            err_lower = err_msg.lower()
            
            # HTTP 451 is always geo-block
            if '451' in err_msg or is_geo_block_error(err_msg):
                print(f"🚫 GEO-BLOCKED: {e}")
                if Config.is_relay_enabled():
                    raise Exception(
                        "🚫 Geo-blocked even through relay.\n"
                        "Your relay server may also be in a blocked region.\n"
                        "Check your Cloudflare Worker deployment region."
                    )
                raise Exception(
                    GEO_BLOCK_MSG + "\n\n💡 Set CLOB_RELAY_URL to bypass. See relay/ folder."
                )
            
            # Auth/session/forbidden errors -> refresh creds and retry once
            if any(kw in err_lower for kw in ('expired', 'unauthorized', 'auth', '401', 'forbidden', '403')):
                print(f"🔄 Auth error ({self._consecutive_errors}x), refreshing: {e}")
                self._refresh_session()
                try:
                    result = method(*args, **kwargs)
                    self._consecutive_errors = 0
                    return result
                except Exception as retry_e:
                    # If retry also gets 451/geo -> that IS geo-block
                    retry_msg = str(retry_e)
                    if '451' in retry_msg or is_geo_block_error(retry_msg):
                        raise Exception(GEO_BLOCK_MSG)
                    print(f"⚠️ Retry also failed: {retry_e}")
                    raise retry_e
            
            raise
    
    async def get_balance(self) -> float:
        """Get USDC balance available for trading."""
        if self.is_paper or not self.clob_client:
            return self._paper_balance
        
        # Use CLOB client's balance-allowance endpoint with proper params
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            # Use per-user sig_type from ClobClient builder, not env var
            builder = getattr(self.clob_client, 'builder', None)
            sig_type = getattr(builder, 'sig_type', Config.SIGNATURE_TYPE) if builder else Config.SIGNATURE_TYPE
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=sig_type
            )
            bal = await asyncio.to_thread(
                self._clob_call, self.clob_client.get_balance_allowance, params
            )
            
            if isinstance(bal, dict):
                raw = float(bal.get('balance', 0))
            else:
                raw = float(bal or 0)
            
            # USDC uses 6 decimals on Polygon — raw value is in micro-USDC
            # e.g. $5 USDC = 5000000 raw, $0.50 = 500000 raw
            # Threshold: anything >= 1000 is definitely raw (= $0.001+)
            usdc = raw / 1e6 if raw >= 1000 else raw
            print(f"💰 Balance: raw={raw}, USDC=${usdc:.6f}")
            return usdc
        except Exception as e:
            print(f"⚠️ CLOB balance error: {e}")
        
        return 0.0
    
    async def get_positions(self) -> List[Position]:
        """Get ACTIVE open positions.
        
        Strategy (improved):
        1. Try Data API first (https://data-api.polymarket.com/positions)
           - Returns only truly open positions with current prices
           - Much more reliable than reconstructing from trades
        2. Fallback: Fetch trades from CLOB → reconstruct → filter
        """
        if self.is_paper or not self.clob_client:
            return self._get_paper_positions()
        
        # ── PRIMARY: Data API (clean, filters resolved markets) ──
        try:
            data_api_positions = await self._get_positions_data_api()
            if data_api_positions:
                print(f"✅ Data API: {len(data_api_positions)} active positions")
                return data_api_positions
            print(f"⚠️ Data API returned empty (all resolved?), falling back to trades")
        except Exception as e:
            print(f"⚠️ Data API error, falling back to trades: {e}")
        
        # ── FALLBACK: Reconstruct from CLOB trades ──
        try:
            all_trades = await asyncio.to_thread(
                self._clob_call, self.clob_client.get_trades
            )
            print(f"📊 Fetched {len(all_trades)} trades from CLOB")
            if not all_trades:
                return []
            
            # Log first trade for debugging
            if isinstance(all_trades[0], dict):
                sample_keys = list(all_trades[0].keys())
                print(f"   ↳ Trade fields: {sample_keys}")
            
            raw_positions = self._positions_from_trades(all_trades)
            if not raw_positions:
                return []
            
            print(f"📦 Raw positions from trades: {len(raw_positions)}")
            
            # Filter out resolved/closed markets
            active_positions = await self._filter_active_positions(raw_positions)
            print(f"✅ Active positions (after filtering resolved): {len(active_positions)}")
            return active_positions
            
        except Exception as e:
            print(f"⚠️ CLOB trades error: {e}")
        
        return []
    
    async def _get_positions_data_api(self) -> List[Position]:
        """Fetch positions from Polymarket Data API.
        
        Uses data-api.polymarket.com/positions endpoint which returns
        positions with current prices and market metadata.
        Filters out resolved/settled markets (price snap to 0 or 1).
        Pattern from PolyFlup (MrRakun35/Poly).
        """
        if not self._funder_address:
            return []
        
        data = await self._fetch_with_retry(
            "https://data-api.polymarket.com/positions",
            params={'user': self._funder_address.lower()},
            timeout=30
        )
        
        if not data or not isinstance(data, list):
            return []
        
        positions = []
        skipped = 0
        for item in data:
            try:
                size = float(item.get('size', 0))
                if size <= 0.001:
                    continue
                
                avg_price = float(item.get('avgPrice', item.get('price', 0.5)))
                cur_price = float(item.get('curPrice', item.get('currentPrice', avg_price)))
                
                # ── Skip resolved/settled markets ──
                # Price snaps to 0 or 1 when market resolves
                if cur_price <= 0.02 or cur_price >= 0.98:
                    title = item.get('title', item.get('question', ''))[:40]
                    print(f"   ⏭️ Skipping settled (price={cur_price:.2f}): {title}")
                    skipped += 1
                    continue
                
                # Skip if API explicitly says resolved/closed
                if item.get('resolved') or item.get('closed'):
                    title = item.get('title', item.get('question', ''))[:40]
                    print(f"   ⏭️ Skipping resolved: {title}")
                    skipped += 1
                    continue
                
                # Skip if end_date has passed
                end_date_str = item.get('endDate', item.get('end_date', ''))
                if end_date_str:
                    try:
                        from datetime import timezone
                        end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                        if end_dt < datetime.now(timezone.utc):
                            title = item.get('title', item.get('question', ''))[:40]
                            print(f"   ⏭️ Skipping ended: {title}")
                            skipped += 1
                            continue
                    except Exception:
                        pass
                
                pnl = (cur_price - avg_price) * size
                pnl_pct = ((cur_price / avg_price) - 1) * 100 if avg_price > 0 else 0
                
                token_id = item.get('asset', item.get('tokenId', item.get('token', '')))
                condition_id = item.get('conditionId', item.get('condition_id', ''))
                
                positions.append(Position(
                    token_id=token_id,
                    condition_id=condition_id,
                    market_question=item.get('title', item.get('question', item.get('market', f'Market {token_id[:8]}...'))),
                    outcome=item.get('outcome', item.get('side', 'Yes')),
                    size=size,
                    avg_price=avg_price,
                    current_price=cur_price,
                    value=cur_price * size,
                    pnl=pnl,
                    pnl_percent=pnl_pct
                ))
            except Exception as e:
                print(f"⚠️ Data API position parse error: {e}")
        
        if skipped:
            print(f"   📊 Filtered out {skipped} resolved/settled positions")
        
        return positions
    
    async def _filter_active_positions(self, positions: List[Position]) -> List[Position]:
        """Filter positions to only include active (non-resolved) markets.
        
        Also enriches each position with:
        - Human-readable market name (from Gamma API)
        - Proper outcome label (Yes/No)
        - Live price, P&L
        
        Four-layer filtering:
        1. CLOB get_market(condition_id) → check accepting_orders, closed, resolved
        2. End-date check → if end_date is in the past, market is done
        3. Gamma API → get readable name + tokens + double-check resolved/end_date
        4. CLOB price check → 0 or 404 means market is gone/resolved
        """
        from datetime import datetime, timezone
        
        active = []
        now_utc = datetime.now(timezone.utc)
        
        # Cache per condition_id: {is_active, question, tokens}
        market_cache: Dict[str, Dict] = {}
        
        for pos in positions:
            cid = pos.condition_id
            
            # ── Step 1: Check market status via CLOB ──
            if cid and cid not in market_cache:
                market_info = {'is_active': True, 'question': '', 'outcome': ''}
                
                # Try CLOB get_market first (fast, has status flags)
                try:
                    market_data = await asyncio.to_thread(
                        self.clob_client.get_market, cid
                    )
                    if isinstance(market_data, dict):
                        accepting = market_data.get('accepting_orders', False)
                        closed = market_data.get('closed', False)
                        resolved = market_data.get('resolved', market_data.get('is_resolved', False))
                        active_flag = market_data.get('active', True)
                        
                        is_active = accepting and not closed and not resolved and active_flag
                        market_info['is_active'] = is_active
                        
                        # Check end_date from CLOB
                        end_date_str = market_data.get('end_date_iso', market_data.get('end_date', ''))
                        if end_date_str and market_info['is_active']:
                            try:
                                end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                                if end_dt < now_utc:
                                    market_info['is_active'] = False
                                    print(f"   ⏭️ End-date passed (CLOB): {end_date_str}")
                            except Exception:
                                pass
                        
                        # CLOB sometimes has question field
                        q = market_data.get('question', market_data.get('description', ''))
                        if q and len(q) > 5:
                            market_info['question'] = q
                        
                        # Map token_ids to outcomes from CLOB market data
                        tokens = market_data.get('tokens', [])
                        for t in tokens:
                            tid = t.get('token_id', '')
                            if tid == pos.token_id:
                                market_info['outcome'] = t.get('outcome', '')
                        
                        if not is_active and market_info['is_active'] is True:
                            pass  # end_date override might have caught it
                        if not market_info['is_active']:
                            reason = []
                            if closed: reason.append('closed')
                            if resolved: reason.append('resolved')
                            if not accepting: reason.append('not accepting orders')
                            if not active_flag: reason.append('inactive')
                            if end_date_str:
                                reason.append(f'end_date={end_date_str}')
                            print(f"   ⏭️ Filtered out: {cid[:16]}... ({', '.join(reason)})")
                except Exception as e:
                    print(f"   ⚠️ CLOB market check error for {cid[:16]}...: {e}")
                
                # ── Step 2: Enrich with Gamma API (human-readable name + end_date) ──
                if market_info['is_active'] or not market_info['question']:
                    try:
                        gamma_data = await self._fetch_with_retry(
                            f"{Config.POLYMARKET_GAMMA_URL}/markets/{cid}",
                            timeout=15
                        )
                        if gamma_data:
                            q = gamma_data.get('question', gamma_data.get('title', ''))
                            if q:
                                market_info['question'] = q
                            
                            # Match token_id to outcome (Yes/No)
                            tokens = gamma_data.get('tokens', [])
                            for t in tokens:
                                tid = t.get('token_id', '')
                                if tid == pos.token_id:
                                    market_info['outcome'] = t.get('outcome', '')
                            
                            # Double-check active status from Gamma
                            if gamma_data.get('closed', False) or gamma_data.get('resolved', False):
                                market_info['is_active'] = False
                                print(f"   ⏭️ Gamma says resolved: {market_info['question'][:50]}")
                            
                            # Check end_date from Gamma (more reliable)
                            if market_info['is_active']:
                                end_date_str = gamma_data.get('end_date_iso', gamma_data.get('endDate', gamma_data.get('end_date', '')))
                                if end_date_str:
                                    try:
                                        end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                                        if end_dt < now_utc:
                                            market_info['is_active'] = False
                                            print(f"   ⏭️ End-date passed (Gamma): {market_info['question'][:40]} ended {end_date_str}")
                                    except Exception:
                                        pass
                                
                                # Also check accepting_order_timestamp / game_start_date
                                # Some markets stop accepting orders when the game starts
                                game_start = gamma_data.get('game_start_date', gamma_data.get('start_date', ''))
                                accepting_orders = gamma_data.get('accepting_orders', True)
                                if isinstance(accepting_orders, bool) and not accepting_orders:
                                    market_info['is_active'] = False
                                    print(f"   ⏭️ Gamma not accepting orders: {market_info['question'][:40]}")
                                elif game_start and market_info['is_active']:
                                    try:
                                        game_dt = datetime.fromisoformat(game_start.replace('Z', '+00:00'))
                                        if game_dt < now_utc:
                                            # Game has started — check if market is still accepting
                                            # Some markets stay open during game, some don't
                                            # Only filter if Gamma explicitly says closed/not-accepting
                                            pass
                                    except Exception:
                                        pass
                            
                            # ── Step 2b: outcomePrices resolution check ──
                            # Pattern from PolyFlup settlement.py: if one outcome price
                            # snaps to >= 0.95 and other <= 0.05, market is effectively resolved
                            if market_info['is_active']:
                                outcome_prices_raw = gamma_data.get('outcomePrices')
                                if outcome_prices_raw:
                                    try:
                                        op = json.loads(outcome_prices_raw) if isinstance(outcome_prices_raw, str) else outcome_prices_raw
                                        if len(op) >= 2:
                                            p0, p1 = float(op[0]), float(op[1])
                                            if (p0 >= 0.95 and p1 <= 0.05) or (p1 >= 0.95 and p0 <= 0.05):
                                                market_info['is_active'] = False
                                                print(f"   ⏭️ Resolved (price snap {p0:.2f}/{p1:.2f}): {market_info['question'][:40]}")
                                    except Exception:
                                        pass
                            
                            # ── Step 2c: enableOrderBook check ──
                            # From Polymarket/agents gamma.py: non-tradable if order book disabled
                            if market_info['is_active']:
                                enable_ob = gamma_data.get('enableOrderBook', True)
                                if isinstance(enable_ob, bool) and not enable_ob:
                                    market_info['is_active'] = False
                                    print(f"   ⏭️ Order book disabled: {market_info['question'][:40]}")
                    except Exception as e:
                        print(f"   ⚠️ Gamma enrichment error: {e}")
                
                market_cache[cid] = market_info
            
            # ── Apply filter ──
            cached = market_cache.get(cid, {})
            if not cached.get('is_active', True):
                continue  # Skip resolved/closed/ended
            
            # ── Enrich position with readable name ──
            if cached.get('question'):
                pos.market_question = cached['question']
            elif not pos.market_question or len(pos.market_question) > 60:
                # Still no name — use short token_id as fallback
                pos.market_question = f"Market {pos.token_id[:8]}..."
            
            if cached.get('outcome'):
                pos.outcome = cached['outcome']
            
            # ── Step 4: Fetch live price ──
            try:
                live_price = await self.get_price(pos.token_id, refresh_from_clob=True)
                if live_price > 0:
                    pos.current_price = live_price
                    pos.value = live_price * pos.size
                    pos.pnl = (live_price - pos.avg_price) * pos.size
                    pos.pnl_percent = ((live_price / pos.avg_price) - 1) * 100 if pos.avg_price > 0 else 0
                else:
                    # Price returned 0 or 404 — likely resolved, skip
                    print(f"   ⏭️ No price for {pos.market_question[:40]} — likely resolved")
                    continue
            except Exception:
                pass  # Keep avg_price as current_price
            
            active.append(pos)
        
        return active
    
    def _parse_gamma_positions(self, data: List[Dict]) -> List[Position]:
        """Parse positions from Gamma API /positions endpoint."""
        positions = []
        for item in data:
            try:
                size = float(item.get('size', 0))
                if size <= 0.001:
                    continue
                
                avg_price = float(item.get('avgPrice', item.get('price', 0.5)))
                current_price = float(item.get('curPrice', item.get('currentPrice', avg_price)))
                pnl = (current_price - avg_price) * size
                pnl_percent = ((current_price / avg_price) - 1) * 100 if avg_price > 0 else 0
                
                # Gamma uses 'asset' or 'token' for token_id
                token_id = item.get('asset', item.get('tokenId', item.get('token', '')))
                
                positions.append(Position(
                    token_id=token_id,
                    condition_id=item.get('conditionId', item.get('condition_id', '')),
                    market_question=item.get('title', item.get('question', item.get('market', 'Unknown'))),
                    outcome=item.get('outcome', item.get('side', 'Yes')),
                    size=size,
                    avg_price=avg_price,
                    current_price=current_price,
                    value=current_price * size,
                    pnl=pnl,
                    pnl_percent=pnl_percent
                ))
            except Exception as e:
                print(f"⚠️ Gamma position parse error: {e}")
        return positions
    
    def _positions_from_trades(self, trades: List[Dict]) -> List[Position]:
        """Reconstruct positions from trade history.
        
        Note: trade['market'] is a condition_id hex hash, NOT a human-readable name.
        We store it as condition_id and resolve the name later via Gamma API.
        """
        # Aggregate trades by token_id
        agg: Dict[str, Dict] = {}
        for trade in trades:
            token_id = trade.get('asset_id', trade.get('tokenID', ''))
            if not token_id:
                continue
            side = trade.get('side', 'BUY').upper()
            size = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            
            if token_id not in agg:
                # trade['market'] is condition_id (hex), NOT a readable name
                condition_id = trade.get('market', trade.get('conditionId', ''))
                agg[token_id] = {
                    'size': 0, 'cost': 0,
                    'question': '',  # Will be resolved from Gamma API later
                    'outcome': trade.get('outcome', trade.get('trader_side', 'Yes')),
                    'condition_id': condition_id
                }
            if side == 'BUY':
                agg[token_id]['cost'] += size * price
                agg[token_id]['size'] += size
            else:
                agg[token_id]['size'] -= size
                agg[token_id]['cost'] -= size * price
        
        positions = []
        for token_id, info in agg.items():
            if info['size'] <= 0.001:
                continue
            avg_price = info['cost'] / info['size'] if info['size'] > 0 else 0.5
            positions.append(Position(
                token_id=token_id,
                condition_id=info['condition_id'],
                market_question=info['question'],  # Empty, enriched in _filter_active_positions
                outcome=info['outcome'],
                size=info['size'],
                avg_price=avg_price,
                current_price=avg_price,
                value=avg_price * info['size'],
                pnl=0,
                pnl_percent=0
            ))
        return positions
    
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
    # LEAGUES & SPORTS DISCOVERY
    # ═══════════════════════════════════════════════════════════════════
    
    async def get_sports_leagues(self, sport: str) -> List[League]:
        """
        Fetch available leagues/series for a sport from the /sports API.
        
        E.g., Cricket → [IPL, T20 World Cup, BBL, ...]
             Football → [EPL, Champions League, La Liga, ...]
        
        Args:
            sport: Sport name (cricket, football, nba, etc.)
        
        Returns:
            List of League objects with series_id for event fetching
        """
        leagues = []
        sport_lower = sport.lower()
        sport_kws = SPORT_KEYWORDS.get(sport_lower, [sport_lower])
        
        try:
            data = await self._fetch_with_retry(
                f"{Config.POLYMARKET_GAMMA_URL}/sports",
                params={},
                timeout=30
            )
            
            if not data:
                print(f"⚠️ /sports API returned no data")
                return leagues
            
            # Filter sports entries matching our sport
            for item in data:
                name = item.get('name', item.get('label', '')).lower()
                slug = item.get('slug', '').lower()
                combined = f"{name} {slug}"
                
                # Match by sport keywords
                if any(kw in combined for kw in sport_kws) or sport_lower in combined:
                    leagues.append(League(
                        series_id=str(item.get('id', item.get('seriesId', ''))),
                        name=item.get('name', item.get('label', 'Unknown League')),
                        sport=sport_lower,
                        slug=item.get('slug', ''),
                        image=item.get('image', ''),
                        event_count=int(item.get('eventCount', item.get('event_count', 0)))
                    ))
            
            print(f"📊 Found {len(leagues)} {sport} leagues from /sports API")
            
        except Exception as e:
            print(f"⚠️ Leagues fetch error: {e}")
        
        return leagues
    
    async def get_events_by_league(self, series_id: str, sport: str = '', limit: int = 15) -> List[Event]:
        """
        Fetch events for a specific league/series.
        
        Results are sorted: 🔴 live first → 🟢 upcoming by date.
        Past / closed events are excluded.

        Args:
            series_id: The series ID from /sports API
            sport: Sport name for keyword validation
            limit: Max events to return
        
        Returns:
            Sorted list of Event objects (live first, then upcoming)
        """
        events = []
        sport_kws = SPORT_KEYWORDS.get(sport.lower(), [sport.lower()]) if sport else []
        
        try:
            data = await self._fetch_with_retry(
                f"{Config.POLYMARKET_GAMMA_URL}/events",
                params={
                    'series_id': series_id,
                    'active': True,
                    'closed': False,
                    'archived': False,
                    'order': 'startDate',
                    'ascending': True,
                    'limit': limit * 3  # fetch extra for post-filter
                },
                timeout=30
            )
            
            if not data:
                return events
            
            if not isinstance(data, list):
                data = [data]
            
            for item in data:
                # Light validation if we have sport keywords
                if sport_kws:
                    parsed = self._parse_event(item, sport.lower(), sport_kws)
                else:
                    parsed = self._parse_event(item, sport.lower(), [])
                
                if parsed:
                    events.append(parsed)
            
            # Filter past & sort: live first → upcoming by date
            events = filter_and_sort_events(events, include_past=False)[:limit]
            
            print(f"📊 Found {len(events)} events for series {series_id} (live+upcoming)")
            
        except Exception as e:
            print(f"⚠️ League events fetch error: {e}")
        
        return events
    
    async def get_tags(self) -> List[Dict]:
        """
        Fetch all available tags/categories from Polymarket.
        Useful for non-automated sports like UFC, Boxing, F1.
        
        Returns:
            List of tag dicts with 'id', 'label', 'slug'
        """
        try:
            data = await self._fetch_with_retry(
                f"{Config.POLYMARKET_GAMMA_URL}/tags",
                params={},
                timeout=30
            )
            if data and isinstance(data, list):
                return data
        except Exception as e:
            print(f"⚠️ Tags fetch error: {e}")
        return []
    
    # ═══════════════════════════════════════════════════════════════════
    # EVENTS & SUB-MARKETS
    # ═══════════════════════════════════════════════════════════════════
    
    async def get_sports_events(self, sport: str, limit: int = 15) -> List[Event]:
        """
        Fetch sports EVENTS (matches) with their sub-markets.
        
        Uses a 3-tier approach for accurate filtering:
        1. Server-side: Use tag_slug parameter for known sport tags
        2. Server-side fallback: Use _q search query on /markets endpoint
        3. Client-side: Keyword validation as final safety net

        Results are sorted: 🔴 live first → 🟢 upcoming by date.
        Past / closed events are excluded.
        """
        events = []
        seen_ids = set()  # Deduplicate across multiple queries
        sport_lower = sport.lower()
        sport_kws = SPORT_KEYWORDS.get(sport_lower, [sport_lower])
        tag_slugs = SPORT_TAG_SLUGS.get(sport_lower, [sport_lower])
        search_queries = SPORT_SEARCH_QUERIES.get(sport_lower, [sport_lower])
        
        # Collect a generous pool of events, filter/sort at the end
        pool_limit = limit * 4  # Fetch more than needed for filtering
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # ═══════════════════════════════════════════════════════════
                # APPROACH 1: Server-side filtering with tag_slug
                # This is the most reliable method - asks API to filter for us
                # ═══════════════════════════════════════════════════════════
                for tag_slug in tag_slugs:
                    if len(events) >= pool_limit:
                        break
                    
                    params = {
                        "tag_slug": tag_slug,
                        "active": True,
                        "closed": False,
                        "archived": False,
                        "order": "startDate",
                        "ascending": True,
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
                    except Exception as e:
                        print(f"⚠️ tag_slug {tag_slug} error: {e}")
                        continue
                
                # ═══════════════════════════════════════════════════════════
                # APPROACH 2: Server-side search with _q parameter on /markets
                # Fallback if tag_slug returns insufficient results
                # ═══════════════════════════════════════════════════════════
                if len(events) < limit:
                    for query in search_queries:
                        if len(events) >= pool_limit:
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
                        "archived": False,
                        "order": "startDate",
                        "ascending": True,
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
                    
        except Exception as e:
            print(f"⚠️ Events fetch error: {e}")
        
        # ═══════════════════════════════════════════════════════════
        # FILTER & SORT: Remove past, sort live-first → upcoming
        # ═══════════════════════════════════════════════════════════
        events = filter_and_sort_events(events, include_past=False)[:limit]
        
        print(f"📊 Found {len(events)} {sport} events (live+upcoming)")
        return events
    
    def _parse_event(self, item: Dict, sport: str, sport_kws: List[str]) -> Optional[Event]:
        """
        Parse an event from API response with keyword validation.
        
        - Extracts start_date / end_date (event-level or earliest sub-market)
        - Sorts sub-markets by category (finals → match → player → prop → other)
        """
        title = item.get('title', item.get('question', ''))
        description = item.get('description', '')
        combined = f"{title} {description}".lower()
        
        # If sport keywords provided, validate (skip for league-fetched events)
        if sport_kws and not any(kw in combined for kw in sport_kws):
            return None
        
        # ── Extract dates from event level ──
        ev_start = item.get('startDate') or item.get('start_date')
        ev_end = item.get('endDate') or item.get('end_date')
        
        # Parse sub-markets
        sub_markets = []
        raw_markets = item.get('markets', [])
        
        # Track earliest sub-market date as fallback
        fallback_start = None
        fallback_end = None
        
        for m in raw_markets:
            tokens = m.get('tokens', [])
            
            # Parse tokens - handle both Yes/No and team-name outcomes
            yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), None)
            no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), None)
            
            # If no Yes/No tokens found, use first/second token (team names etc.)
            outcome_yes = 'Yes'
            outcome_no = 'No'
            if not yes_token and len(tokens) >= 1:
                yes_token = tokens[0]
                outcome_yes = tokens[0].get('outcome', 'Yes')
            if not no_token and len(tokens) >= 2:
                no_token = tokens[1]
                outcome_no = tokens[1].get('outcome', 'No')
            
            yes_token = yes_token or {}
            no_token = no_token or {}
            
            # Get token IDs (with clobTokenIds fallback)
            yes_token_id = yes_token.get('token_id', '')
            no_token_id = no_token.get('token_id', '')
            
            if not yes_token_id or not no_token_id:
                clob_ids = m.get('clobTokenIds')
                if clob_ids:
                    try:
                        ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                        if len(ids) >= 2:
                            if not yes_token_id: yes_token_id = ids[0]
                            if not no_token_id: no_token_id = ids[1]
                    except Exception:
                        pass
            
            # Try to get prices from outcomePrices if tokens don't have them
            yes_price = float(yes_token.get('price', 0.5))
            no_price = float(no_token.get('price', 0.5))
            
            outcome_prices = m.get('outcomePrices')
            if outcome_prices and (yes_price == 0.5 or no_price == 0.5):
                try:
                    prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                    if len(prices) >= 2:
                        yes_price = float(prices[0])
                        no_price = float(prices[1])
                except Exception:
                    pass
            
            # Capture sub-market dates as fallback for event dates
            m_start = m.get('startDateIso') or m.get('startDate')
            m_end = m.get('endDateIso') or m.get('endDate')
            if m_start and (not fallback_start or m_start < fallback_start):
                fallback_start = m_start
            if m_end and (not fallback_end or m_end > fallback_end):
                fallback_end = m_end
            
            sub_markets.append(SubMarket(
                condition_id=m.get('conditionId', m.get('id', '')),
                question=m.get('question', m.get('groupItemTitle', 'Unknown')),
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                yes_price=yes_price,
                no_price=no_price,
                group_item_title=m.get('groupItemTitle', ''),
                outcome_yes=outcome_yes,
                outcome_no=outcome_no
            ))
        
        # If no sub-markets, create one from event itself
        if not sub_markets:
            tokens = item.get('tokens', [])
            yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), None)
            no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), None)
            
            oe_yes, oe_no = 'Yes', 'No'
            if not yes_token and len(tokens) >= 1:
                yes_token = tokens[0]
                oe_yes = tokens[0].get('outcome', 'Yes')
            if not no_token and len(tokens) >= 2:
                no_token = tokens[1]
                oe_no = tokens[1].get('outcome', 'No')
            yes_token = yes_token or {}
            no_token = no_token or {}
            
            # clobTokenIds fallback
            ytid = yes_token.get('token_id', '')
            ntid = no_token.get('token_id', '')
            if not ytid or not ntid:
                cids = item.get('clobTokenIds')
                if cids:
                    try:
                        ids = json.loads(cids) if isinstance(cids, str) else cids
                        if len(ids) >= 2:
                            if not ytid: ytid = ids[0]
                            if not ntid: ntid = ids[1]
                    except Exception:
                        pass
            
            sub_markets.append(SubMarket(
                condition_id=item.get('conditionId', item.get('id', '')),
                question=title,
                yes_token_id=ytid,
                no_token_id=ntid,
                yes_price=float(yes_token.get('price', 0.5)),
                no_price=float(no_token.get('price', 0.5)),
                group_item_title='Match Winner',
                outcome_yes=oe_yes,
                outcome_no=oe_no
            ))
        
        # ── Sort sub-markets by category priority ──
        cat_order = {'finals': 0, 'match': 1, 'player': 2, 'series': 3, 'prop': 4, 'other': 5}
        sub_markets.sort(key=lambda s: cat_order.get(categorize_sub_market(s.group_item_title), 5))
        
        # Use event-level dates, falling back to sub-market dates
        final_start = ev_start or fallback_start
        final_end = ev_end or fallback_end
        
        return Event(
            event_id=item.get('id', ''),
            title=title,
            description=description,
            sport=sport,
            start_date=final_start,
            end_date=final_end,
            markets=sub_markets
        )
    
    def _market_to_event(self, item: Dict, sport: str) -> Optional[Event]:
        """Convert a market to an Event with a single sub-market."""
        question = item.get('question', '')
        tokens = item.get('tokens', [])
        
        # Handle both Yes/No and team-name outcomes
        yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), None)
        no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), None)
        
        outcome_yes, outcome_no = 'Yes', 'No'
        if not yes_token and len(tokens) >= 1:
            yes_token = tokens[0]
            outcome_yes = tokens[0].get('outcome', 'Yes')
        if not no_token and len(tokens) >= 2:
            no_token = tokens[1]
            outcome_no = tokens[1].get('outcome', 'No')
        yes_token = yes_token or {}
        no_token = no_token or {}
        
        # Get token IDs with clobTokenIds fallback
        ytid = yes_token.get('token_id', '')
        ntid = no_token.get('token_id', '')
        if not ytid or not ntid:
            clob_ids = item.get('clobTokenIds')
            if clob_ids:
                try:
                    ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                    if len(ids) >= 2:
                        if not ytid: ytid = ids[0]
                        if not ntid: ntid = ids[1]
                except Exception:
                    pass
        
        # Try outcomePrices if prices are default
        yes_price = float(yes_token.get('price', 0.5))
        no_price = float(no_token.get('price', 0.5))
        
        outcome_prices = item.get('outcomePrices')
        if outcome_prices and (yes_price == 0.5 or no_price == 0.5):
            try:
                prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                if len(prices) >= 2:
                    yes_price = float(prices[0])
                    no_price = float(prices[1])
            except Exception:
                pass
        
        sub_market = SubMarket(
            condition_id=item.get('conditionId', item.get('id', '')),
            question=question,
            yes_token_id=ytid,
            no_token_id=ntid,
            yes_price=yes_price,
            no_price=no_price,
            group_item_title=item.get('groupItemTitle', 'Market'),
            outcome_yes=outcome_yes,
            outcome_no=outcome_no
        )
        
        return Event(
            event_id=item.get('conditionId', item.get('id', '')),
            title=question,
            description=item.get('description', ''),
            sport=sport,
            start_date=item.get('startDateIso') or item.get('startDate'),
            end_date=item.get('endDateIso') or item.get('endDate'),
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
        """Search for markets by keyword.
        
        Enhanced: filters by enableOrderBook=true for tradable markets,
        uses outcomePrices for accurate pricing,
        validates ALL query words appear in results to avoid irrelevant matches.
        """
        # Stop words to ignore in keyword validation
        STOP_WORDS = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'will', 'in', 'on',
                       'at', 'to', 'for', 'of', 'and', 'or', 'vs', 'with', 'who', 'what',
                       'when', 'how', 'be', 'by', 'from', 'it', 'this', 'that'}
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                params = {
                    "limit": limit * 5,  # fetch extra for keyword filtering
                    "active": active_only,
                    "closed": False,
                    "archived": False,
                    "enableOrderBook": True,
                    "_q": query
                }
                
                resp = await client.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/markets",
                    params=params
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    markets = self._parse_markets(data)
                    
                    # Keyword validation: ensure ALL significant query words appear in results
                    query_words = [w.lower() for w in query.split() if w.lower() not in STOP_WORDS]
                    if query_words:
                        filtered = []
                        for m in markets:
                            text = f"{m.question} {m.description}".lower()
                            if all(w in text for w in query_words):
                                filtered.append(m)
                        # If too aggressive (no results), fall back to requiring ANY word
                        if not filtered:
                            for m in markets:
                                text = f"{m.question} {m.description}".lower()
                                if any(w in text for w in query_words):
                                    filtered.append(m)
                        markets = filtered if filtered else markets
                    
                    # Try refreshing stale prices from CLOB midpoint
                    for m in markets:
                        if m.yes_price == 0.5 and m.no_price == 0.5 and m.yes_token_id:
                            try:
                                mid = await self.get_price(m.yes_token_id)
                                if mid > 0 and mid != 0.5:
                                    m.yes_price = mid
                                    m.no_price = round(1.0 - mid, 4)
                            except Exception:
                                pass
                    
                    return markets[:limit]
                    
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
        """Parse markets from API response.
        
        Enhanced: uses outcomePrices field when token prices are stale (0.5),
        filters non-tradable markets, handles non-Yes/No outcomes (team names),
        and uses clobTokenIds as fallback for token IDs.
        """
        markets = []
        
        for item in data:
            try:
                # Skip non-tradable markets (from Polymarket/agents gamma.py pattern)
                if item.get('closed', False) or item.get('archived', False):
                    continue
                enable_ob = item.get('enableOrderBook', True)
                if isinstance(enable_ob, bool) and not enable_ob:
                    continue
                accepting = item.get('accepting_orders', item.get('acceptingOrders', True))
                if isinstance(accepting, bool) and not accepting:
                    continue
                
                tokens = item.get('tokens', [])
                question = item.get('question', 'Unknown')
                description = item.get('description', '')
                
                # Handle both Yes/No and team-name outcomes
                yes_token = next((t for t in tokens if t.get('outcome', '').lower() == 'yes'), None)
                no_token = next((t for t in tokens if t.get('outcome', '').lower() == 'no'), None)
                
                if not yes_token and len(tokens) >= 1:
                    yes_token = tokens[0]
                if not no_token and len(tokens) >= 2:
                    no_token = tokens[1]
                yes_token = yes_token or {}
                no_token = no_token or {}
                
                # Get token IDs with clobTokenIds fallback
                ytid = yes_token.get('token_id', '')
                ntid = no_token.get('token_id', '')
                if not ytid or not ntid:
                    clob_ids = item.get('clobTokenIds')
                    if clob_ids:
                        try:
                            ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                            if len(ids) >= 2:
                                if not ytid: ytid = ids[0]
                                if not ntid: ntid = ids[1]
                        except Exception:
                            pass
                
                # Get prices from tokens
                yes_price = float(yes_token.get('price', 0.5))
                no_price = float(no_token.get('price', 0.5))
                
                # If prices look stale (both default 0.5), try outcomePrices field
                if yes_price == 0.5 and no_price == 0.5:
                    outcome_prices = item.get('outcomePrices')
                    if outcome_prices:
                        try:
                            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                            if len(prices) >= 2:
                                yes_price = float(prices[0])
                                no_price = float(prices[1])
                        except Exception:
                            pass
                
                # Get actual outcome labels
                oe_yes = yes_token.get('outcome', 'Yes') if yes_token else 'Yes'
                oe_no = no_token.get('outcome', 'No') if no_token else 'No'
                
                markets.append(Market(
                    condition_id=item.get('conditionId', item.get('id', '')),
                    question=question,
                    description=description,
                    yes_token_id=ytid,
                    no_token_id=ntid,
                    yes_price=yes_price,
                    no_price=no_price,
                    volume=float(item.get('volume', 0)),
                    category=item.get('category', 'Other'),
                    sport=detect_sport(f"{question} {description}"),
                    end_date=item.get('endDate'),
                    outcome_yes=oe_yes,
                    outcome_no=oe_no
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
        Execute a market buy order using FAK (Fill-And-Kill) strategy.
        
        FAK allows partial fills — whatever can be filled at market is executed,
        the rest is cancelled. Much better fill rates than FOK (all-or-nothing).
        Pattern from PolyFlup (MrRakun35/Poly).
        
        Strategy:
        1. FAK market order (partial fills OK, best execution)
        2. If FAK returns 0 fill → retry once with fresh price
        3. Fallback: GTC limit at best ask + slippage
        
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
        
        # Get actual sig type from ClobClient's OrderBuilder
        builder = getattr(self.clob_client, 'builder', None)
        actual_sig_type = getattr(builder, 'sig_type', '?') if builder else '?'
        actual_funder = getattr(builder, 'funder', getattr(self, '_funder_address', '?')) if builder else getattr(self, '_funder_address', '?')
        signer_addr = '?'
        try:
            signer_addr = self.clob_client.get_address()
        except Exception:
            pass
        print(f"🔑 Buy order: sig_type={actual_sig_type}, funder={str(actual_funder)[:16]}..., signer={str(signer_addr)[:16]}...")
        
        # NOTE: API creds already set during /unlock. Do NOT refresh here —
        # calling create_or_derive_api_creds() before every buy adds latency
        # and can cause race conditions. Creds are valid for the session lifetime.
        
        # Sync on-chain USDC allowance with CLOB API (reference: 5min_trade repo)
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            ba_sig = getattr(builder, 'sig_type', Config.SIGNATURE_TYPE) if builder else Config.SIGNATURE_TYPE
            ba_params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=ba_sig,
            )
            self.clob_client.update_balance_allowance(ba_params)
        except Exception as e:
            print(f"⚠️ update_balance_allowance: {e}")
        
        last_error = ""
        
        # ═══════════════════════════════════════════════════
        # STEP 1: FAK market order (up to 2 attempts)
        # ═══════════════════════════════════════════════════
        for attempt in range(2):
            try:
                order = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount_usd,
                    side=BUY
                )
                
                signed = self._clob_call(self.clob_client.create_market_order, order)
                resp = self._clob_call(self.clob_client.post_order, signed, OrderType.FAK)
                
                success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
                
                if success:
                    order_id = resp.get('orderID', resp.get('order_id', '')) if isinstance(resp, dict) else getattr(resp, 'orderID', getattr(resp, 'order_id', ''))
                    
                    # FAK response: check size_matched for actual fill amount
                    filled = 0.0
                    for key in ('size_matched', 'filled', 'filledSize', 'sizeMatched'):
                        val = resp.get(key, 0) if isinstance(resp, dict) else getattr(resp, key, 0)
                        if val:
                            filled = float(val)
                            break
                    
                    avg_price = 0.0
                    for key in ('avgPrice', 'average_price', 'averagePrice'):
                        val = resp.get(key, 0) if isinstance(resp, dict) else getattr(resp, key, 0)
                        if val:
                            avg_price = float(val)
                            break
                    
                    print(f"✅ FAK buy filled: {filled} shares @ {avg_price} (attempt {attempt+1})")
                    return OrderResult(
                        success=True,
                        order_id=str(order_id),
                        filled_size=filled if filled else 0,
                        avg_price=avg_price if avg_price else 0
                    )
                else:
                    last_error = resp.get('error', resp.get('errorMsg', 'FAK order failed')) if isinstance(resp, dict) else getattr(resp, 'error', getattr(resp, 'errorMsg', 'FAK order failed'))
                    print(f"⚠️ FAK buy attempt {attempt+1} failed: {last_error}")
                    
            except Exception as e:
                last_error = str(e)
                print(f"⚠️ FAK buy attempt {attempt+1} error: {e}")
                if 'invalid signature' in str(e).lower():
                    print(f"   💡 ClobClient sig_type={actual_sig_type}, funder={str(actual_funder)[:16]}...")
                    print(f"   💡 If sell works but buy doesn't, try /connect again with correct wallet type")
            
            # Brief pause before retry
            if attempt == 0:
                await asyncio.sleep(0.5)
        
        # ═══════════════════════════════════════════════════
        # STEP 2: GTC limit fallback at best ask + slippage
        # ═══════════════════════════════════════════════════
        try:
            best_ask = await self.get_best_ask(token_id)
            if best_ask and best_ask > 0.01:
                limit_price = min(best_ask * (1 + slippage / 100), 0.99)
                shares = amount_usd / limit_price
                
                order_args = OrderArgs(
                    token_id=token_id,
                    price=round(limit_price, 2),
                    size=round(shares, 2),
                    side=BUY
                )
                signed = self._clob_call(self.clob_client.create_order, order_args)
                resp = self._clob_call(self.clob_client.post_order, signed, OrderType.GTC)
                
                success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
                
                if success:
                    order_id = resp.get('orderID', resp.get('order_id', '')) if isinstance(resp, dict) else getattr(resp, 'orderID', getattr(resp, 'order_id', ''))
                    print(f"✅ GTC buy limit placed at {limit_price*100:.0f}¢")
                    return OrderResult(
                        success=True,
                        order_id=str(order_id),
                        filled_size=0,  # GTC may not fill immediately
                        avg_price=limit_price
                    )
        except Exception as e:
            print(f"⚠️ GTC buy fallback error: {e}")
            if 'invalid signature' in str(e).lower():
                print(f"   💡 ClobClient sig_type={actual_sig_type}, funder={str(actual_funder)[:16]}...")
                print(f"   💡 Try: /connect again and ensure correct wallet type")
            last_error = str(e)
        
        return OrderResult(success=False, error=str(last_error))
    
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
            
            signed = self._clob_call(self.clob_client.create_order, order_args)
            
            # Post as GTC (Good 'Til Cancelled)
            resp = self._clob_call(self.clob_client.post_order, signed, OrderType.GTC)
            
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
            
            signed = self._clob_call(self.clob_client.create_order, order_args)
            resp = self._clob_call(self.clob_client.post_order, signed, OrderType.GTC)
            
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
                # Pass token_id string directly (BookParams causes stringification bugs in some versions)
                try:
                    book = self.clob_client.get_order_book(token_id)
                except TypeError:
                    # Some py-clob-client versions require BookParams
                    params = BookParams(token_id=token_id)
                    book = self.clob_client.get_order_book(params)
                
                # Parse response — handle both dict and OrderSummary/object responses
                bids = []
                asks = []
                
                if isinstance(book, dict):
                    raw_bids = book.get('bids', [])
                    raw_asks = book.get('asks', [])
                else:
                    raw_bids = getattr(book, 'bids', []) or []
                    raw_asks = getattr(book, 'asks', []) or []
                
                for bid in raw_bids[:depth]:
                    if isinstance(bid, dict):
                        price = float(bid.get('price', 0))
                        size = float(bid.get('size', 0))
                    elif hasattr(bid, 'price'):
                        price = float(bid.price)
                        size = float(getattr(bid, 'size', 0))
                    else:
                        try:
                            price = float(bid[0])
                            size = float(bid[1])
                        except (IndexError, TypeError):
                            continue
                    bids.append({'price': price, 'size': size})
                
                for ask in raw_asks[:depth]:
                    if isinstance(ask, dict):
                        price = float(ask.get('price', 0))
                        size = float(ask.get('size', 0))
                    elif hasattr(ask, 'price'):
                        price = float(ask.price)
                        size = float(getattr(ask, 'size', 0))
                    else:
                        try:
                            price = float(ask[0])
                            size = float(ask[1])
                        except (IndexError, TypeError):
                            continue
                    asks.append({'price': price, 'size': size})
                
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
            
            orders = self._clob_call(self.clob_client.get_orders, params)
            
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
            resp = self._clob_call(self.clob_client.cancel, order_id)
            
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
                resp = self._clob_call(self.clob_client.cancel_market_orders, market_id)
            else:
                resp = self._clob_call(self.clob_client.cancel_all)
            
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
    
    async def estimate_sell_execution(self, token_id: str, shares: float) -> Dict[str, float]:
        """Estimate sell execution: VWAP, slippage, fees, net proceeds.
        
        Reads orderbook to calculate volume-weighted average price for
        the given sell size. Shows what the user will actually receive.
        
        Returns:
            dict with keys: vwap, slippage_pct, fee_pct, fee_usd, 
                           gross_proceeds, net_proceeds, best_bid, book_depth
        """
        from core.position_manager import calc_fee
        
        best_bid = await self.get_best_bid(token_id)
        if best_bid <= 0:
            return {'vwap': 0, 'slippage_pct': 0, 'fee_pct': 0, 'fee_usd': 0,
                    'gross_proceeds': 0, 'net_proceeds': 0, 'best_bid': 0, 'book_depth': 0}
        
        # Try to get full orderbook for VWAP
        vwap = best_bid
        book_depth_shares = 0
        try:
            book = await self.get_order_book(token_id, depth=20)
            bids = book.get('bids', [])
            if bids:
                # Calculate VWAP across bid levels
                remaining = shares
                total_cost = 0.0
                total_filled = 0.0
                for level in bids:
                    level_price = float(level['price'])
                    level_size = float(level['size'])
                    book_depth_shares += level_size
                    fill = min(remaining, level_size)
                    total_cost += fill * level_price
                    total_filled += fill
                    remaining -= fill
                    if remaining <= 0:
                        break
                
                if total_filled > 0:
                    vwap = total_cost / total_filled
        except Exception:
            pass
        
        slippage_pct = ((best_bid - vwap) / best_bid * 100) if best_bid > 0 else 0
        fee_pct = calc_fee(vwap) * 100  # Dynamic fee at sell price
        gross_proceeds = vwap * shares
        fee_usd = gross_proceeds * calc_fee(vwap)
        net_proceeds = gross_proceeds - fee_usd
        
        return {
            'vwap': vwap,
            'slippage_pct': slippage_pct,
            'fee_pct': fee_pct,
            'fee_usd': fee_usd,
            'gross_proceeds': gross_proceeds,
            'net_proceeds': net_proceeds,
            'best_bid': best_bid,
            'book_depth': book_depth_shares
        }
    
    async def sell_market(
        self, 
        token_id: str, 
        shares: Optional[float] = None,
        percent: float = 100
    ) -> OrderResult:
        """
        Execute a market sell order with FAK-first routing.
        
        Strategy:
        1. FAK sell (partial fills OK, no minimum, best for small positions)
        2. FOK sell (all-or-nothing fallback)
        3. GTC at best_bid (last resort for large positions ≥5 shares)
        4. GTC at best_bid - 1¢ (desperation fallback)
        """
        if self.is_paper or not self.clob_client:
            return await self._paper_sell(token_id, shares, percent)
        
        try:
            if shares is None:
                positions = await self.get_positions()
                pos = next((p for p in positions if p.token_id == token_id), None)
                if not pos:
                    return OrderResult(success=False, error="Position not found")
                shares = pos.size * (percent / 100)
            
            if shares <= 0:
                return OrderResult(success=False, error="Nothing to sell")
            
            # Set conditional token allowance before selling (required for proxy wallets)
            # Reference: 5min_trade _ensure_conditional_allowance pattern
            try:
                from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                builder = getattr(self.clob_client, 'builder', None)
                ba_sig = getattr(builder, 'sig_type', Config.SIGNATURE_TYPE) if builder else Config.SIGNATURE_TYPE
                cond_params = BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=token_id,
                    signature_type=ba_sig,
                )
                self.clob_client.update_balance_allowance(cond_params)
            except Exception as e:
                print(f"⚠️ Conditional allowance update: {e}")
            
            # ═══════════════════════════════════════════════════
            # STEP 1: FAK sell (partial fills OK), then FOK
            # FAK is more likely to succeed than FOK (all-or-nothing)
            # Works for any size (no 5-share minimum)
            # ═══════════════════════════════════════════════════
            if Config.ENABLE_FOK_ORDERS:
                for order_type in (OrderType.FAK, OrderType.FOK):
                    try:
                        order = MarketOrderArgs(
                            token_id=token_id,
                            amount=shares,
                            side=SELL
                        )
                        signed = self.clob_client.create_market_order(order)
                        resp = self.clob_client.post_order(signed, order_type)
                        
                        success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
                        
                        if success:
                            order_id = resp.get('orderID', resp.get('order_id', '')) if isinstance(resp, dict) else getattr(resp, 'orderID', getattr(resp, 'order_id', ''))
                            
                            # Check size_matched for actual fill (FAK may be partial)
                            filled = 0.0
                            for key in ('size_matched', 'filled', 'filledSize', 'sizeMatched'):
                                val = resp.get(key, 0) if isinstance(resp, dict) else getattr(resp, key, 0)
                                if val:
                                    filled = float(val)
                                    break
                            if not filled:
                                filled = shares
                            
                            avg_price = 0.0
                            for key in ('avgPrice', 'average_price', 'averagePrice'):
                                val = resp.get(key, 0) if isinstance(resp, dict) else getattr(resp, key, 0)
                                if val:
                                    avg_price = float(val)
                                    break
                            
                            ot_name = 'FAK' if order_type == OrderType.FAK else 'FOK'
                            print(f"✅ {ot_name} sell filled: {filled} shares @ {avg_price}")
                            return OrderResult(
                                success=True,
                                order_id=str(order_id),
                                filled_size=filled,
                                avg_price=avg_price
                            )
                        else:
                            ot_name = 'FAK' if order_type == OrderType.FAK else 'FOK'
                            print(f"⚠️ {ot_name} sell failed, trying next...")
                    except Exception as e:
                        ot_name = 'FAK' if order_type == OrderType.FAK else 'FOK'
                        print(f"⚠️ {ot_name} sell error: {e}, trying next...")
            
            # ═══════════════════════════════════════════════════
            # STEP 2: GTC limit at best bid price (last resort)
            # Only for remaining shares if FAK partially filled
            # ═══════════════════════════════════════════════════
            if Config.FOK_SELL_FALLBACK_GTC:
                best_bid = await self.get_best_bid(token_id)
                if best_bid and best_bid > 0.01:
                    for attempt in range(Config.MAX_SELL_RETRIES):
                        try:
                            sell_price = best_bid if attempt == 0 else max(0.01, best_bid - Config.GTC_FALLBACK_DISCOUNT)
                            
                            order_args = OrderArgs(
                                token_id=token_id,
                                price=sell_price,
                                size=shares,
                                side=SELL
                            )
                            signed = self._clob_call(self.clob_client.create_order, order_args)
                            resp = self._clob_call(self.clob_client.post_order, signed, OrderType.GTC)
                            
                            success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
                            
                            if success:
                                order_id = resp.get('orderID', resp.get('order_id', '')) if isinstance(resp, dict) else getattr(resp, 'orderID', getattr(resp, 'order_id', ''))
                                print(f"✅ GTC sell placed at {sell_price*100:.0f}¢ (attempt {attempt+1})")
                                return OrderResult(
                                    success=True,
                                    order_id=str(order_id),
                                    filled_size=0,  # GTC may not fill immediately
                                    avg_price=sell_price
                                )
                        except Exception as e:
                            print(f"⚠️ GTC sell attempt {attempt+1} error: {e}")
                            continue
            
            return OrderResult(success=False, error="All sell attempts failed (FOK + GTC)")
                
        except Exception as e:
            return OrderResult(success=False, error=str(e))
    
    async def instant_sell(
        self,
        token_id: str,
        shares: Optional[float] = None,
        percent: float = 100
    ) -> OrderResult:
        """
        Instant sell — designed for one-click Telegram button.
        Same as sell_market but with extra logging and speed optimization.
        """
        import time
        start = time.time()
        result = await self.sell_market(token_id, shares, percent)
        elapsed = (time.time() - start) * 1000
        
        if result.success:
            print(f"⚡ Instant sell completed in {elapsed:.0f}ms")
        else:
            print(f"❌ Instant sell failed in {elapsed:.0f}ms: {result.error}")
        
        return result
    
    async def get_best_bid(self, token_id: str) -> float:
        """Get the best bid price (what you receive when selling)."""
        # Try WS cache first (fastest)
        try:
            from core.ws_client import get_ws_client
            ws = get_ws_client()
            bid = ws.get_best_bid(token_id)
            if bid and bid > 0:
                return bid
        except Exception:
            pass
        
        # Try order book
        try:
            book = await self.get_order_book(token_id, depth=1)
            bids = book.get('bids', [])
            if bids:
                return float(bids[0]['price'])
        except Exception:
            pass
        
        # Fallback to midpoint
        return await self.get_price(token_id)
    
    async def get_best_ask(self, token_id: str) -> float:
        """Get the best ask price (what you pay when buying)."""
        # Try WS cache first
        try:
            from core.ws_client import get_ws_client
            ws = get_ws_client()
            ask = ws.get_best_ask(token_id)
            if ask and ask > 0:
                return ask
        except Exception:
            pass
        
        # Try order book
        try:
            book = await self.get_order_book(token_id, depth=1)
            asks = book.get('asks', [])
            if asks:
                return float(asks[0]['price'])
        except Exception:
            pass
        
        # Fallback to midpoint
        return await self.get_price(token_id)
    
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
        Also runs a geo-block check for live mode.
        """
        if self.is_paper:
            await self._load_paper_positions()
        elif self.clob_client:
            # Quick connectivity check: hit CLOB /time (no auth needed, fast)
            clob_url = Config.get_clob_url()
            relay = " (via relay)" if Config.is_relay_enabled() else ""
            try:
                headers = {}
                if Config.is_relay_enabled() and Config.CLOB_RELAY_AUTH_TOKEN:
                    headers['Authorization'] = f'Bearer {Config.CLOB_RELAY_AUTH_TOKEN}'
                
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(f"{clob_url}/time", headers=headers)
                    if resp.status_code == 451:
                        print(f"🚫 Warning: CLOB /time returned 451 (geo-blocked){relay}")
                        print(GEO_BLOCK_MSG)
                        if not Config.is_relay_enabled():
                            print("\n💡 TIP: Set CLOB_RELAY_URL to bypass. See relay/ folder.\n")
                    elif resp.status_code == 403:
                        print(f"⚠️ CLOB /time returned 403 (may be auth issue, not blocking){relay}")
                    else:
                        print(f"🌍 CLOB connectivity OK (/time = {resp.status_code}){relay}")
            except Exception as e:
                print(f"⚠️ CLOB connectivity check failed{relay}: {e}")


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


def get_user_client(telegram_id: int) -> Optional[PolymarketClient]:
    """Get a PolymarketClient using a specific user's ClobClient.
    
    Creates a lightweight clone of the shared client that uses the
    user's ClobClient from UserManager for authenticated operations,
    while sharing the Gamma API session and caches.
    
    Returns None if user has no active (unlocked) session.
    """
    from core.user_manager import get_user_manager
    um = get_user_manager()
    
    session = um.get_session(telegram_id)
    if not session or not session.clob_client:
        return None
    
    # Clone the shared client but swap ClobClient
    shared = get_polymarket_client()
    user_client = PolymarketClient.__new__(PolymarketClient)
    user_client.__dict__.update(shared.__dict__)
    user_client.clob_client = session.clob_client
    user_client.is_paper = False
    user_client._funder_address = session.funder_address or ''
    
    return user_client


async def require_auth(update) -> Optional[PolymarketClient]:
    """Get authenticated client for the calling user, or send error message.
    
    Usage in handlers:
        client = await require_auth(update)
        if not client:
            return
    """
    from core.user_manager import get_user_manager
    
    user_id = update.effective_user.id
    client = get_user_client(user_id)
    if client:
        return client
    
    # Determine why auth failed
    um = get_user_manager()
    if await um.is_registered(user_id):
        msg = "🔒 Session locked. Use /unlock to unlock your wallet."
    else:
        msg = "🔗 No wallet connected. Use /connect to link your wallet."
    
    if update.callback_query:
        await update.callback_query.answer(msg, show_alert=True)
    elif update.message:
        await update.message.reply_text(msg)
    
    return None
