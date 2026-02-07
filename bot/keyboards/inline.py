"""
Inline Keyboards

All inline keyboard builders for the Telegram bot.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Optional


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main menu keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Positions", callback_data="positions"),
            InlineKeyboardButton("💰 Balance", callback_data="balance")
        ],
        [
            InlineKeyboardButton("🛒 Buy", callback_data="buy"),
            InlineKeyboardButton("🔍 Search", callback_data="search")
        ],
        [
            InlineKeyboardButton("⭐ Favorites", callback_data="favorites"),
            InlineKeyboardButton("🔥 Hot Markets", callback_data="hot")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def positions_keyboard(positions: list) -> InlineKeyboardMarkup:
    """Keyboard for positions list."""
    keyboard = []
    
    for i, pos in enumerate(positions[:10]):  # Max 10 positions
        pnl_emoji = "📈" if pos.pnl >= 0 else "📉"
        short_question = pos.market_question[:25] + "..." if len(pos.market_question) > 25 else pos.market_question
        
        keyboard.append([
            InlineKeyboardButton(
                f"{pnl_emoji} {short_question}",
                callback_data=f"pos_detail_{i}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔙 Menu", callback_data="menu"),
        InlineKeyboardButton("🔄 Refresh", callback_data="positions")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def position_detail_keyboard(token_id: str, has_shares: bool = True) -> InlineKeyboardMarkup:
    """Keyboard for position details with sell options."""
    keyboard = []
    
    if has_shares:
        keyboard.append([
            InlineKeyboardButton("💯 Sell 100%", callback_data=f"sell_{token_id}_100"),
            InlineKeyboardButton("50%", callback_data=f"sell_{token_id}_50")
        ])
        keyboard.append([
            InlineKeyboardButton("25%", callback_data=f"sell_{token_id}_25"),
            InlineKeyboardButton("✏️ Custom", callback_data=f"sell_{token_id}_custom")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔙 Positions", callback_data="positions"),
        InlineKeyboardButton("⭐ Favorite", callback_data=f"fav_add_{token_id}")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def sell_confirm_keyboard(token_id: str, percent: int) -> InlineKeyboardMarkup:
    """Confirm sell action keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Sell", callback_data=f"confirm_sell_{token_id}_{percent}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"pos_detail_{token_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def category_keyboard() -> InlineKeyboardMarkup:
    """Category selection for buying."""
    keyboard = [
        [
            InlineKeyboardButton("🏈 Sports", callback_data="cat_sports"),
            InlineKeyboardButton("🗳️ Politics", callback_data="cat_politics")
        ],
        [
            InlineKeyboardButton("🪙 Crypto", callback_data="cat_crypto"),
            InlineKeyboardButton("🎬 Entertainment", callback_data="cat_entertainment")
        ],
        [InlineKeyboardButton("🔙 Menu", callback_data="menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def sports_keyboard() -> InlineKeyboardMarkup:
    """Sports selection keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("🏏 Cricket", callback_data="sport_cricket"),
            InlineKeyboardButton("⚽ Football", callback_data="sport_football")
        ],
        [
            InlineKeyboardButton("🏀 NBA", callback_data="sport_nba"),
            InlineKeyboardButton("🎾 Tennis", callback_data="sport_tennis")
        ],
        [
            InlineKeyboardButton("🥊 UFC/MMA", callback_data="sport_ufc"),
            InlineKeyboardButton("🏈 NFL", callback_data="sport_nfl")
        ],
        [InlineKeyboardButton("🔙 Categories", callback_data="buy")]
    ]
    return InlineKeyboardMarkup(keyboard)


def markets_keyboard(markets: list, page: int = 0, page_size: int = 5) -> InlineKeyboardMarkup:
    """Keyboard for market selection."""
    keyboard = []
    
    start = page * page_size
    end = start + page_size
    page_markets = markets[start:end]
    
    for i, market in enumerate(page_markets):
        short_q = market.question[:30] + "..." if len(market.question) > 30 else market.question
        keyboard.append([
            InlineKeyboardButton(
                f"📊 {short_q}",
                callback_data=f"market_{market.condition_id}"
            )
        ])
    
    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
    if end < len(markets):
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="buy")])
    
    return InlineKeyboardMarkup(keyboard)


def outcome_keyboard(condition_id: str, yes_price: float, no_price: float) -> InlineKeyboardMarkup:
    """Yes/No outcome selection."""
    keyboard = [
        [
            InlineKeyboardButton(
                f"✅ YES ({yes_price*100:.0f}¢)",
                callback_data=f"outcome_{condition_id}_yes"
            ),
            InlineKeyboardButton(
                f"❌ NO ({no_price*100:.0f}¢)",
                callback_data=f"outcome_{condition_id}_no"
            )
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="buy")]
    ]
    return InlineKeyboardMarkup(keyboard)


def amount_keyboard(token_id: str) -> InlineKeyboardMarkup:
    """Amount selection for buying."""
    keyboard = [
        [
            InlineKeyboardButton("$10", callback_data=f"amount_{token_id}_10"),
            InlineKeyboardButton("$25", callback_data=f"amount_{token_id}_25"),
            InlineKeyboardButton("$50", callback_data=f"amount_{token_id}_50")
        ],
        [
            InlineKeyboardButton("$100", callback_data=f"amount_{token_id}_100"),
            InlineKeyboardButton("✏️ Custom", callback_data=f"amount_{token_id}_custom")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="buy")]
    ]
    return InlineKeyboardMarkup(keyboard)


def buy_confirm_keyboard(token_id: str, amount: float) -> InlineKeyboardMarkup:
    """Confirm buy action keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("🚀 EXECUTE BUY", callback_data=f"exec_buy_{token_id}_{amount}"),
            InlineKeyboardButton("❌ Cancel", callback_data="buy")
        ],
        [
            InlineKeyboardButton("⭐ Add Favorite", callback_data=f"fav_add_{token_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def favorites_keyboard(favorites: list) -> InlineKeyboardMarkup:
    """Favorites list keyboard."""
    keyboard = []
    
    for fav in favorites[:10]:
        short_label = fav.label[:25] + "..." if len(fav.label) > 25 else fav.label
        keyboard.append([
            InlineKeyboardButton(
                f"⭐ {short_label} ({fav.outcome})",
                callback_data=f"fav_view_{fav.market_id}"
            ),
            InlineKeyboardButton("🗑️", callback_data=f"fav_del_{fav.id}")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔙 Menu", callback_data="menu")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def search_results_keyboard(markets: list) -> InlineKeyboardMarkup:
    """Search results keyboard."""
    keyboard = []
    
    for market in markets[:8]:
        short_q = market.question[:28] + "..." if len(market.question) > 28 else market.question
        keyboard.append([
            InlineKeyboardButton(
                f"📊 {short_q}",
                callback_data=f"market_{market.condition_id}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔙 Menu", callback_data="menu"),
        InlineKeyboardButton("🔍 New Search", callback_data="search")
    ])
    
    return InlineKeyboardMarkup(keyboard)
