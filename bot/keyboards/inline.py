"""
Inline Keyboards

All keyboard layouts for the Telegram bot.
Supports events with sub-markets for sports betting.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Any


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main menu buttons."""
    return InlineKeyboardMarkup([
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
            InlineKeyboardButton("🔥 Hot", callback_data="hot")
        ]
    ])


def positions_keyboard(positions: List[Any]) -> InlineKeyboardMarkup:
    """List of positions with index-based callbacks."""
    buttons = []
    
    for idx, pos in enumerate(positions[:10]):
        pnl_emoji = "📈" if pos.pnl >= 0 else "📉"
        label = f"{pnl_emoji} {pos.market_question[:30]}..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"pos_{idx}")])
    
    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


def position_detail_keyboard(pos_index: int) -> InlineKeyboardMarkup:
    """Position detail with sell options."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 Sell 25%", callback_data=f"sell_{pos_index}_25"),
            InlineKeyboardButton("📤 Sell 50%", callback_data=f"sell_{pos_index}_50")
        ],
        [
            InlineKeyboardButton("📤 Sell 100%", callback_data=f"sell_{pos_index}_100"),
            InlineKeyboardButton("✏️ Custom", callback_data=f"sell_{pos_index}_c")
        ],
        [InlineKeyboardButton("🔙 Positions", callback_data="positions")]
    ])


def sell_confirm_keyboard(pos_index: int, percent: int) -> InlineKeyboardMarkup:
    """Sell confirmation."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Sell", callback_data=f"csell_{pos_index}_{percent}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"pos_{pos_index}")]
    ])


def category_keyboard() -> InlineKeyboardMarkup:
    """Category selection."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆 Sports", callback_data="cat_sports")],
        [
            InlineKeyboardButton("🏛️ Politics", callback_data="cat_politics"),
            InlineKeyboardButton("₿ Crypto", callback_data="cat_crypto")
        ],
        [
            InlineKeyboardButton("🎬 Entertainment", callback_data="cat_ent"),
            InlineKeyboardButton("📈 Finance", callback_data="cat_finance")
        ],
        [InlineKeyboardButton("🔙 Menu", callback_data="menu")]
    ])


def sports_keyboard() -> InlineKeyboardMarkup:
    """Sports selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏏 Cricket", callback_data="sp_cricket"),
            InlineKeyboardButton("⚽ Football", callback_data="sp_football")
        ],
        [
            InlineKeyboardButton("🏀 NBA", callback_data="sp_nba"),
            InlineKeyboardButton("🏈 NFL", callback_data="sp_nfl")
        ],
        [
            InlineKeyboardButton("🎾 Tennis", callback_data="sp_tennis"),
            InlineKeyboardButton("🥊 UFC", callback_data="sp_ufc")
        ],
        [InlineKeyboardButton("🔙 Categories", callback_data="buy")]
    ])


def events_keyboard(events: List[Any], page: int = 0) -> InlineKeyboardMarkup:
    """
    Events list keyboard (matches/games).
    Shows events with number of sub-markets available.
    """
    buttons = []
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_events = events[start:end]
    
    for idx, event in enumerate(page_events):
        real_idx = start + idx
        sub_count = len(event.markets) if hasattr(event, 'markets') else 0
        
        # Truncate title and show sub-market count
        title = event.title[:35] + "..." if len(event.title) > 35 else event.title
        if sub_count > 1:
            label = f"📋 {title} ({sub_count} bets)"
        else:
            label = f"📋 {title}"
        
        buttons.append([InlineKeyboardButton(label, callback_data=f"evt_{real_idx}")])
    
    # Pagination
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"evp_{page - 1}"))
    if end < len(events):
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"evp_{page + 1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("🔙 Sports", callback_data="cat_sports")])
    return InlineKeyboardMarkup(buttons)


def sub_markets_keyboard(sub_markets: List[Any], event_idx: int) -> InlineKeyboardMarkup:
    """
    Sub-markets within an event.
    Shows options like: Match Winner, Toss Winner, Top Scorer, Over/Under
    """
    buttons = []
    
    for idx, sub in enumerate(sub_markets[:8]):  # Max 8 sub-markets
        # Get a short label
        if sub.group_item_title:
            label = sub.group_item_title[:35]
        else:
            label = sub.question[:35] if len(sub.question) > 35 else sub.question
        
        # Show price indicator
        yes_pct = int(sub.yes_price * 100)
        label = f"📊 {label} ({yes_pct}%)"
        
        buttons.append([InlineKeyboardButton(label, callback_data=f"sub_{event_idx}_{idx}")])
    
    buttons.append([InlineKeyboardButton("🔙 Events", callback_data="back_events")])
    return InlineKeyboardMarkup(buttons)


def outcome_keyboard() -> InlineKeyboardMarkup:
    """Yes/No outcome selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ YES", callback_data="out_yes"),
            InlineKeyboardButton("❌ NO", callback_data="out_no")
        ],
        [InlineKeyboardButton("⭐ Add Favorite", callback_data="fav_add")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_sub")]
    ])


def amount_keyboard() -> InlineKeyboardMarkup:
    """Amount selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("$5", callback_data="amt_5"),
            InlineKeyboardButton("$10", callback_data="amt_10"),
            InlineKeyboardButton("$25", callback_data="amt_25")
        ],
        [
            InlineKeyboardButton("$50", callback_data="amt_50"),
            InlineKeyboardButton("$100", callback_data="amt_100"),
            InlineKeyboardButton("✏️ Custom", callback_data="amt_c")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_out")]
    ])


def buy_confirm_keyboard() -> InlineKeyboardMarkup:
    """Buy confirmation."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Execute Buy", callback_data="exec_buy")],
        [InlineKeyboardButton("❌ Cancel", callback_data="buy")]
    ])


def favorites_keyboard(favorites: List[Any]) -> InlineKeyboardMarkup:
    """Favorites list."""
    buttons = []
    
    for idx, fav in enumerate(favorites[:8]):
        label = f"⭐ {fav.label[:35]}..."
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"fv_{idx}"),
            InlineKeyboardButton("🗑️", callback_data=f"fd_{idx}")
        ])
    
    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


def search_results_keyboard(markets: List[Any]) -> InlineKeyboardMarkup:
    """Search results - single markets (not events)."""
    buttons = []
    
    for idx, market in enumerate(markets[:8]):
        title = market.question[:40] + "..." if len(market.question) > 40 else market.question
        buttons.append([InlineKeyboardButton(f"📊 {title}", callback_data=f"mkt_{idx}")])
    
    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


# Keep legacy markets_keyboard for backward compatibility
def markets_keyboard(markets: List[Any], page: int = 0) -> InlineKeyboardMarkup:
    """Legacy markets keyboard for non-event markets."""
    return search_results_keyboard(markets)
