"""
Polymarket Telegram Bot Configuration

All settings with environment variable overrides.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Central configuration for the Polymarket Telegram bot."""
    
    # ═══════════════════════════════════════════════════════════════════
    # TELEGRAM
    # ═══════════════════════════════════════════════════════════════════
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')  # Restrict to specific user
    
    # ═══════════════════════════════════════════════════════════════════
    # POLYMARKET WALLET
    # ═══════════════════════════════════════════════════════════════════
    POLYGON_PRIVATE_KEY = os.getenv('POLYGON_PRIVATE_KEY', '')
    FUNDER_ADDRESS = os.getenv('FUNDER_ADDRESS', '')
    SIGNATURE_TYPE = int(os.getenv('SIGNATURE_TYPE', '1'))  # 0=EOA, 1=Magic/Email, 2=Proxy
    
    # ═══════════════════════════════════════════════════════════════════
    # API ENDPOINTS
    # ═══════════════════════════════════════════════════════════════════
    POLYMARKET_CLOB_URL = os.getenv('POLYMARKET_CLOB_URL', 'https://clob.polymarket.com')
    POLYMARKET_GAMMA_URL = os.getenv('POLYMARKET_GAMMA_URL', 'https://gamma-api.polymarket.com')
    POLYGON_CHAIN_ID = int(os.getenv('POLYGON_CHAIN_ID', '137'))
    
    # ═══════════════════════════════════════════════════════════════════
    # TRADING SETTINGS
    # ═══════════════════════════════════════════════════════════════════
    TRADING_MODE = os.getenv('TRADING_MODE', 'paper')  # 'paper' or 'live'
    DEFAULT_SLIPPAGE = float(os.getenv('DEFAULT_SLIPPAGE', '2.0'))
    MAX_TRADE_USD = float(os.getenv('MAX_TRADE_USD', '100'))
    MIN_TRADE_USD = float(os.getenv('MIN_TRADE_USD', '1'))
    
    # ═══════════════════════════════════════════════════════════════════
    # INSTANT SELL & FOK SETTINGS
    # ═══════════════════════════════════════════════════════════════════
    USE_INSTANT_SELL = os.getenv('USE_INSTANT_SELL', 'true').lower() == 'true'
    ENABLE_FOK_ORDERS = os.getenv('ENABLE_FOK_ORDERS', 'true').lower() == 'true'
    FOK_SELL_FALLBACK_GTC = os.getenv('FOK_SELL_FALLBACK_GTC', 'true').lower() == 'true'
    GTC_FALLBACK_DISCOUNT = float(os.getenv('GTC_FALLBACK_DISCOUNT', '0.01'))  # 1¢ lower
    MAX_SELL_RETRIES = int(os.getenv('MAX_SELL_RETRIES', '3'))
    
    # ═══════════════════════════════════════════════════════════════════
    # WEBSOCKET & REAL-TIME
    # ═══════════════════════════════════════════════════════════════════
    POLYMARKET_WS_URL = os.getenv('POLYMARKET_WS_URL', 'wss://ws-subscriptions-clob.polymarket.com/ws/market')
    POSITION_REFRESH_INTERVAL = float(os.getenv('POSITION_REFRESH_INTERVAL', '10'))
    ENABLE_LIVE_POSITION_UPDATES = os.getenv('ENABLE_LIVE_POSITION_UPDATES', 'true').lower() == 'true'
    
    # ═══════════════════════════════════════════════════════════════════
    # FEATURES
    # ═══════════════════════════════════════════════════════════════════
    ENABLE_PRICE_ALERTS = os.getenv('ENABLE_PRICE_ALERTS', 'true').lower() == 'true'
    ENABLE_FAVORITES = os.getenv('ENABLE_FAVORITES', 'true').lower() == 'true'
    
    # ═══════════════════════════════════════════════════════════════════
    # SPORTS / CATEGORIES
    # ═══════════════════════════════════════════════════════════════════
    SPORTS_PRIORITY = [s.strip() for s in os.getenv('SPORTS_PRIORITY', 'cricket,football,nba,tennis,ufc').split(',')]
    
    SPORT_EMOJIS = {
        'cricket': '🏏',
        'football': '⚽',
        'soccer': '⚽',
        'nba': '🏀',
        'basketball': '🏀',
        'tennis': '🎾',
        'ufc': '🥊',
        'mma': '🥊',
        'nfl': '🏈',
        'mlb': '⚾',
        'baseball': '⚾',
        'hockey': '🏒',
        'nhl': '🏒',
        'golf': '⛳',
        'f1': '🏎️',
        'formula-1': '🏎️',
        'politics': '🗳️',
        'crypto': '🪙',
        'entertainment': '🎬'
    }
    
    # ═══════════════════════════════════════════════════════════════════
    # DATABASE
    # ═══════════════════════════════════════════════════════════════════
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'data/favorites.db')
    
    @classmethod
    def is_paper_mode(cls) -> bool:
        """Check if running in paper trading mode."""
        return cls.TRADING_MODE.lower() == 'paper'
    
    @classmethod
    def is_configured(cls) -> bool:
        """Check if essential config is set."""
        return bool(cls.TELEGRAM_BOT_TOKEN and cls.POLYGON_PRIVATE_KEY)
    
    @classmethod
    def get_sport_emoji(cls, sport: str) -> str:
        """Get emoji for a sport."""
        return cls.SPORT_EMOJIS.get(sport.lower(), '🎯')
    
    @classmethod
    def print_status(cls):
        """Print configuration status."""
        print("\n" + "=" * 50)
        print("🤖 POLYMARKET TELEGRAM BOT")
        print("=" * 50)
        print(f"📊 Mode: {'PAPER' if cls.is_paper_mode() else '🔴 LIVE'} TRADING")
        print(f"⚡ Instant Sell: {'ON' if cls.USE_INSTANT_SELL else 'OFF'}")
        print(f"📡 WebSocket: {'ON' if cls.POLYMARKET_WS_URL else 'OFF'}")
        print(f"📱 Telegram: {'✅' if cls.TELEGRAM_BOT_TOKEN else '❌'}")
        print(f"🔐 Wallet: {'✅' if cls.POLYGON_PRIVATE_KEY else '❌'}")
        print(f"💳 Funder: {'✅' if cls.FUNDER_ADDRESS else '❌'}")
        print(f"🎯 Sports: {', '.join(cls.SPORTS_PRIORITY)}")
        print("=" * 50 + "\n")
