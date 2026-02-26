"""
Inline Keyboards

All keyboard layouts for the Telegram bot.
Supports events with sub-markets for sports betting.
Shows event timing status (🔴 LIVE / 🟢 Upcoming) and date info.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Any
from datetime import datetime


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
    """List of positions with instant sell buttons."""
    buttons = []
    
    for idx, pos in enumerate(positions[:10]):
        pnl_emoji = "🟢" if pos.pnl >= 0 else "🔴"
        pnl_str = f"+${pos.pnl:.1f}" if pos.pnl >= 0 else f"-${abs(pos.pnl):.1f}"
        label = f"{pnl_emoji} {pos.market_question[:25]}.. {pnl_str}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"pos_{idx}"),
            InlineKeyboardButton("⚡SELL", callback_data=f"isell_{idx}_100")
        ])
    
    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="refresh_positions"),
        InlineKeyboardButton("🔙 Menu", callback_data="menu")
    ])
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


def instant_sell_keyboard(pos_index: int) -> InlineKeyboardMarkup:
    """
    Position detail with instant sell buttons.
    One-click sell at 25%, 50%, or 100% — NO confirmation step.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ SELL 100%", callback_data=f"isell_{pos_index}_100"),
        ],
        [
            InlineKeyboardButton("⚡ 50%", callback_data=f"isell_{pos_index}_50"),
            InlineKeyboardButton("⚡ 25%", callback_data=f"isell_{pos_index}_25"),
        ],
        [
            InlineKeyboardButton("📤 Custom %", callback_data=f"sell_{pos_index}_c"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"pos_{pos_index}"),
            InlineKeyboardButton("🔙 Positions", callback_data="positions"),
        ]
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
            InlineKeyboardButton("🥊 UFC/MMA", callback_data="sp_ufc")
        ],
        [
            InlineKeyboardButton("⚾ MLB", callback_data="sp_baseball"),
            InlineKeyboardButton("🏒 NHL", callback_data="sp_hockey")
        ],
        [
            InlineKeyboardButton("🏎️ F1", callback_data="sp_f1"),
            InlineKeyboardButton("⛳ Golf", callback_data="sp_golf")
        ],
        [InlineKeyboardButton("🔙 Categories", callback_data="buy")]
    ])


def leagues_keyboard(leagues: List[Any], sport: str = '') -> InlineKeyboardMarkup:
    """
    League/series selection within a sport.
    E.g., Cricket → IPL, T20 World Cup, BBL, PSL
    """
    buttons = []
    
    for idx, league in enumerate(leagues[:10]):
        name = league.name if hasattr(league, 'name') else str(league)
        event_count = league.event_count if hasattr(league, 'event_count') else 0
        
        if event_count > 0:
            label = f"🏆 {name} ({event_count} events)"
        else:
            label = f"🏆 {name}"
        
        buttons.append([InlineKeyboardButton(label, callback_data=f"lg_{idx}")])
    
    # Add "All Events" option to skip league filter
    buttons.append([InlineKeyboardButton("📋 All Events (no filter)", callback_data="lg_all")])
    buttons.append([InlineKeyboardButton("🔙 Sports", callback_data="cat_sports")])
    return InlineKeyboardMarkup(buttons)


def search_prompt_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown during search input prompt."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="menu")]
    ])


def events_keyboard(events: List[Any], page: int = 0) -> InlineKeyboardMarkup:
    """
    Events list keyboard (matches/games).
    Shows events with timing status (🔴 LIVE / 🟢 Upcoming) and date.
    """
    buttons = []
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_events = events[start:end]
    
    for idx, event in enumerate(page_events):
        real_idx = start + idx
        sub_count = len(event.markets) if hasattr(event, 'markets') else 0
        
        # ── Determine timing badge ──
        status_badge = ""
        date_hint = ""
        if hasattr(event, 'start_date') and event.start_date:
            try:
                from core.polymarket_client import event_status, parse_event_date
                st = event_status(event.start_date, getattr(event, 'end_date', None))
                if st == 'live':
                    status_badge = "🔴 "
                elif st == 'upcoming':
                    status_badge = "🟢 "
                    dt = parse_event_date(event.start_date)
                    if dt:
                        now = datetime.utcnow()
                        diff = (dt.replace(tzinfo=None) - now).days
                        if diff == 0:
                            date_hint = " (Today)"
                        elif diff == 1:
                            date_hint = " (Tomorrow)"
                        elif 1 < diff <= 7:
                            date_hint = f" ({dt.strftime('%a')})"
                        else:
                            date_hint = f" ({dt.strftime('%d %b')})"
            except Exception:
                pass
        
        # Truncate title and show sub-market count
        max_title = 28
        title = event.title[:max_title] + "..." if len(event.title) > max_title else event.title
        
        if sub_count > 1:
            label = f"{status_badge}📋 {title}{date_hint} ({sub_count})"
        else:
            label = f"{status_badge}📋 {title}{date_hint}"
        
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
    Also shows outcome names (e.g., India 65% / Pakistan 35%)
    """
    buttons = []
    
    # Category emoji map
    cat_emoji = {
        'finals': '🏆',
        'match': '⚔️',
        'player': '🏅',
        'series': '📊',
        'prop': '🎲',
        'other': '📊',
    }
    
    for idx, sub in enumerate(sub_markets[:10]):  # Max 10 sub-markets
        # Categorize
        try:
            from core.polymarket_client import categorize_sub_market
            cat = categorize_sub_market(sub.group_item_title)
        except Exception:
            cat = 'other'
        emoji = cat_emoji.get(cat, '📊')
        
        # Get a short label
        if sub.group_item_title:
            label = sub.group_item_title[:30]
        else:
            label = sub.question[:30] if len(sub.question) > 30 else sub.question
        
        # Show outcome names and prices for team-based markets
        oe_yes = getattr(sub, 'outcome_yes', 'Yes')
        oe_no = getattr(sub, 'outcome_no', 'No')
        yes_pct = int(sub.yes_price * 100)
        no_pct = int(sub.no_price * 100)
        
        if oe_yes != 'Yes' and oe_no != 'No':
            # Team-based market: show both teams with odds
            label = f"{emoji} {label}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"sub_{event_idx}_{idx}")])
            # Add small odds line
            odds_label = f"   {oe_yes} {yes_pct}% | {oe_no} {no_pct}%"
            buttons.append([InlineKeyboardButton(odds_label, callback_data=f"sub_{event_idx}_{idx}")])
        else:
            label = f"{emoji} {label} ({yes_pct}%)"
            buttons.append([InlineKeyboardButton(label, callback_data=f"sub_{event_idx}_{idx}")])
    
    buttons.append([InlineKeyboardButton("🔙 Events", callback_data="back_events")])
    return InlineKeyboardMarkup(buttons)


def outcome_keyboard(outcome_yes: str = "Yes", outcome_no: str = "No") -> InlineKeyboardMarkup:
    """Outcome selection - shows actual team names or Yes/No."""
    yes_emoji = "✅" if outcome_yes == "Yes" else "🔵"
    no_emoji = "❌" if outcome_no == "No" else "🔴"
    
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{yes_emoji} {outcome_yes}", callback_data="out_yes"),
            InlineKeyboardButton(f"{no_emoji} {outcome_no}", callback_data="out_no")
        ],
        [InlineKeyboardButton("⭐ Add Favorite", callback_data="fav_add")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_sub")]
    ])


def amount_keyboard() -> InlineKeyboardMarkup:
    """Amount selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("$1", callback_data="amt_1"),
            InlineKeyboardButton("$2", callback_data="amt_2"),
            InlineKeyboardButton("$5", callback_data="amt_5"),
            InlineKeyboardButton("$10", callback_data="amt_10")
        ],
        [
            InlineKeyboardButton("$25", callback_data="amt_25"),
            InlineKeyboardButton("$50", callback_data="amt_50"),
            InlineKeyboardButton("$100", callback_data="amt_100"),
            InlineKeyboardButton("✏️ Custom", callback_data="amt_custom")
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
