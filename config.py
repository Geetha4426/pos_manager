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
    MIN_TRADE_USD = float(os.getenv('MIN_TRADE_USD', '5'))
    
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
        'hockey': '🏒',
        'golf': '⛳',
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
        print(f"📱 Telegram: {'✅' if cls.TELEGRAM_BOT_TOKEN else '❌'}")
        print(f"🔐 Wallet: {'✅' if cls.POLYGON_PRIVATE_KEY else '❌'}")
        print(f"💳 Funder: {'✅' if cls.FUNDER_ADDRESS else '❌'}")
        print(f"🎯 Sports: {', '.join(cls.SPORTS_PRIORITY)}")
        print("=" * 50 + "\n")
