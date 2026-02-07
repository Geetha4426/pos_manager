"""
Trading Handlers

Handles /buy command with EVENT-based sports navigation.
Shows: Sport → Events (matches) → Sub-Markets (toss, top scorer, etc.) → Yes/No
"""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import Config
from core.polymarket_client import get_polymarket_client
from bot.keyboards.inline import (
    category_keyboard, sports_keyboard, events_keyboard, sub_markets_keyboard,
    outcome_keyboard, amount_keyboard, buy_confirm_keyboard, markets_keyboard
)


# Conversation states
CUSTOM_AMOUNT = 0


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /buy command - start buy flow."""
    text = """
🛒 <b>Buy Position</b>

Select a category to browse markets:
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=category_keyboard()
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=category_keyboard()
        )


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection."""
    query = update.callback_query
    await query.answer()
    
    category = query.data.split('_')[1]  # cat_sports -> sports
    context.user_data['category'] = category
    
    if category == 'sports':
        text = """
🏆 <b>Select Sport</b>

Choose a sport to see available matches:
"""
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=sports_keyboard()
        )
    else:
        # For non-sports, search directly
        client = get_polymarket_client()
        cat_query = 'entertainment' if category == 'ent' else category
        markets = await client.search_markets(cat_query, limit=15)
        context.user_data['markets'] = markets
        
        if not markets:
            await query.edit_message_text(
                f"📭 No active {category} markets found.\n\nTry /search <query>",
                reply_markup=category_keyboard()
            )
            return
        
        text = f"""
📊 <b>{category.title()} Markets</b>

Found {len(markets)} markets:
"""
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=markets_keyboard(markets)
        )


async def sport_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sport selection - fetch EVENTS (matches)."""
    query = update.callback_query
    await query.answer("🔍 Loading events...")
    
    sport = query.data.split('_')[1]  # sp_cricket -> cricket
    context.user_data['sport'] = sport
    
    sport_emoji = Config.get_sport_emoji(sport)
    
    client = get_polymarket_client()
    
    # Fetch EVENTS (not just markets)
    events = await client.get_sports_events(sport=sport, limit=15)
    context.user_data['events'] = events
    
    if not events:
        await query.edit_message_text(
            f"📭 No active {sport.upper()} events found.\n\nTry /search {sport}",
            reply_markup=sports_keyboard()
        )
        return
    
    text = f"""
{sport_emoji} <b>{sport.upper()} Events</b>

Found {len(events)} active matches/events:

<i>Tap an event to see betting options</i>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=events_keyboard(events)
    )


async def events_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle events pagination."""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.split('_')[1])  # evp_1 -> 1
    events = context.user_data.get('events', [])
    sport = context.user_data.get('sport', 'sports')
    sport_emoji = Config.get_sport_emoji(sport)
    
    text = f"""
{sport_emoji} <b>{sport.upper()} Events</b>

Found {len(events)} active matches (Page {page + 1}):
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=events_keyboard(events, page=page)
    )


async def event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle event selection - show SUB-MARKETS."""
    query = update.callback_query
    await query.answer()
    
    # Get event by index
    idx = int(query.data.split('_')[1])  # evt_0 -> 0
    events = context.user_data.get('events', [])
    
    if idx >= len(events):
        await query.edit_message_text("⚠️ Event not found. Try again with /buy")
        return
    
    event = events[idx]
    context.user_data['selected_event'] = event
    context.user_data['selected_event_index'] = idx
    
    sub_markets = event.markets
    
    if not sub_markets:
        await query.edit_message_text(
            f"📭 No betting options found for this event.\n\nTry another match.",
            reply_markup=events_keyboard(events)
        )
        return
    
    text = f"""
📊 <b>{event.title}</b>

<b>Available Betting Options:</b>

<i>Select a market to trade:</i>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=sub_markets_keyboard(sub_markets, idx)
    )


async def sub_market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sub-market selection - show Yes/No."""
    query = update.callback_query
    await query.answer()
    
    # Parse: sub_0_1 -> event_idx=0, sub_idx=1
    parts = query.data.split('_')
    event_idx = int(parts[1])
    sub_idx = int(parts[2])
    
    events = context.user_data.get('events', [])
    if event_idx >= len(events):
        await query.edit_message_text("⚠️ Event not found. Start over with /buy")
        return
    
    event = events[event_idx]
    sub_markets = event.markets
    
    if sub_idx >= len(sub_markets):
        await query.edit_message_text("⚠️ Market not found. Start over with /buy")
        return
    
    sub = sub_markets[sub_idx]
    context.user_data['selected_sub_market'] = sub
    context.user_data['selected_market'] = sub  # Legacy compatibility
    
    # Calculate implied probabilities
    yes_prob = sub.yes_price * 100
    no_prob = sub.no_price * 100
    
    text = f"""
📊 <b>Market Details</b>

📋 <b>{event.title}</b>
🎯 <b>{sub.group_item_title or sub.question}</b>

💹 <b>Prices:</b>
   ✅ YES: {yes_prob:.0f}¢ (${sub.yes_price:.2f})
   ❌ NO: {no_prob:.0f}¢ (${sub.no_price:.2f})

<b>Select your position:</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard()
    )


async def back_events_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to events list."""
    query = update.callback_query
    await query.answer()
    
    events = context.user_data.get('events', [])
    sport = context.user_data.get('sport', 'sports')
    sport_emoji = Config.get_sport_emoji(sport)
    
    text = f"""
{sport_emoji} <b>{sport.upper()} Events</b>

Found {len(events)} active matches:
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=events_keyboard(events)
    )


async def back_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to sub-markets."""
    query = update.callback_query
    await query.answer()
    
    event = context.user_data.get('selected_event')
    event_idx = context.user_data.get('selected_event_index', 0)
    
    if not event:
        await back_events_callback(update, context)
        return
    
    text = f"""
📊 <b>{event.title}</b>

<b>Available Betting Options:</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=sub_markets_keyboard(event.markets, event_idx)
    )


async def outcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle outcome selection (Yes/No) - show amount options."""
    query = update.callback_query
    await query.answer()
    
    outcome = query.data.split('_')[1].upper()  # out_yes -> YES
    
    sub = context.user_data.get('selected_sub_market')
    if not sub:
        await query.edit_message_text("⚠️ Market not found. Start over with /buy")
        return
    
    # Get the correct token and price
    if outcome == 'YES':
        token_id = sub.yes_token_id
        price = sub.yes_price
    else:
        token_id = sub.no_token_id
        price = sub.no_price
    
    context.user_data['selected_token_id'] = token_id
    context.user_data['selected_outcome'] = outcome
    context.user_data['selected_price'] = price
    
    event = context.user_data.get('selected_event')
    event_title = event.title if event else sub.question
    
    text = f"""
💵 <b>Enter Amount</b>

📋 {event_title}
🎯 <b>{sub.group_item_title or sub.question}</b>
📍 <b>Buying:</b> {outcome} @ ${price:.2f}

<b>Select amount (USD):</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=amount_keyboard()
    )


async def back_out_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to outcome selection."""
    query = update.callback_query
    await query.answer()
    
    sub = context.user_data.get('selected_sub_market')
    event = context.user_data.get('selected_event')
    
    if not sub:
        await buy_command(update, context)
        return
    
    yes_prob = sub.yes_price * 100
    no_prob = sub.no_price * 100
    
    event_title = event.title if event else sub.question
    
    text = f"""
📊 <b>Market Details</b>

📋 <b>{event_title}</b>
🎯 <b>{sub.group_item_title or sub.question}</b>

💹 <b>Prices:</b>
   ✅ YES: {yes_prob:.0f}¢
   ❌ NO: {no_prob:.0f}¢

<b>Select your position:</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard()
    )


async def amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount selection - show confirmation."""
    query = update.callback_query
    await query.answer()
    
    amount_str = query.data.split('_')[1]  # amt_10 -> 10
    
    if amount_str == 'c':  # custom
        await query.edit_message_text(
            "✏️ <b>Custom Amount</b>\n\nEnter amount in USD (min $5, max $100):",
            parse_mode='HTML'
        )
        return CUSTOM_AMOUNT
    
    amount = float(amount_str)
    return await show_buy_confirmation(query, context, amount)


async def show_buy_confirmation(query, context, amount: float):
    """Show buy confirmation screen."""
    sub = context.user_data.get('selected_sub_market')
    event = context.user_data.get('selected_event')
    outcome = context.user_data.get('selected_outcome', 'YES')
    price = context.user_data.get('selected_price', 0.5)
    
    if not sub:
        await query.edit_message_text("⚠️ Market not found. Start over with /buy")
        return
    
    est_shares = amount / price if price > 0 else 0
    
    context.user_data['buy_amount'] = amount
    
    mode_text = "📝 PAPER" if Config.is_paper_mode() else "💱 LIVE"
    event_title = event.title if event else sub.question
    
    text = f"""
🚀 <b>Confirm Buy Order</b>

📋 <b>{event_title}</b>
🎯 <b>{sub.group_item_title or sub.question}</b>

📍 <b>Outcome:</b> {outcome}
💵 <b>Price:</b> ${price:.4f}
💰 <b>Amount:</b> ${amount:.2f}
📦 <b>Est. Shares:</b> {est_shares:.2f}

<b>Mode:</b> {mode_text}

<i>🔥 Market order = instant execution</i>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=buy_confirm_keyboard()
    )


async def execute_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the buy order."""
    query = update.callback_query
    await query.answer("⚡ Executing buy...")
    
    token_id = context.user_data.get('selected_token_id')
    amount = context.user_data.get('buy_amount')
    sub = context.user_data.get('selected_sub_market')
    event = context.user_data.get('selected_event')
    outcome = context.user_data.get('selected_outcome', 'YES')
    
    if not token_id or not amount:
        await query.edit_message_text("⚠️ Session expired. Use /buy to start over.")
        return
    
    market_info = {
        'condition_id': sub.condition_id if sub else '',
        'question': event.title if event else (sub.question if sub else 'Unknown'),
        'outcome': outcome
    }
    
    client = get_polymarket_client()
    result = await client.buy_market(token_id, amount, market_info=market_info)
    
    if result.success:
        event_title = event.title if event else (sub.question if sub else 'Position')
        sub_title = sub.group_item_title or sub.question if sub else ''
        
        text = f"""
✅ <b>Buy Executed!</b>

📋 {event_title}
🎯 {sub_title}
📍 <b>Outcome:</b> {outcome}

📦 <b>Shares:</b> {result.filled_size:.2f}
💵 <b>Avg Price:</b> ${result.avg_price:.4f}
🆔 <b>Order ID:</b> <code>{result.order_id[:16]}...</code>

{'📝 Paper trade' if Config.is_paper_mode() else '💱 Live trade'}

Use /positions to view your position.
"""
    else:
        text = f"""
❌ <b>Buy Failed</b>

Error: {result.error}

Please try again.
"""
    
    await query.edit_message_text(text, parse_mode='HTML')


# Legacy market_callback for non-event markets (search results)
async def market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle market selection from search results."""
    query = update.callback_query
    await query.answer()
    
    idx = int(query.data.split('_')[1])  # mkt_0 -> 0
    markets = context.user_data.get('markets', [])
    
    if idx >= len(markets):
        await query.edit_message_text("⚠️ Market not found. Try again with /buy")
        return
    
    market = markets[idx]
    
    # Convert to sub-market for compatibility
    from core.polymarket_client import SubMarket
    sub = SubMarket(
        condition_id=market.condition_id,
        question=market.question,
        yes_token_id=market.yes_token_id,
        no_token_id=market.no_token_id,
        yes_price=market.yes_price,
        no_price=market.no_price,
        group_item_title=''
    )
    
    context.user_data['selected_sub_market'] = sub
    context.user_data['selected_market'] = market
    context.user_data['selected_event'] = None  # No parent event
    
    yes_prob = market.yes_price * 100
    no_prob = market.no_price * 100
    
    text = f"""
📊 <b>Market Details</b>

📋 <b>{market.question}</b>

💹 <b>Prices:</b>
   ✅ YES: {yes_prob:.0f}¢ (${market.yes_price:.2f})
   ❌ NO: {no_prob:.0f}¢ (${market.no_price:.2f})

📈 <b>Volume:</b> ${market.volume:,.0f}

<b>Select your position:</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard()
    )


async def page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle legacy pagination."""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.split('_')[1])
    markets = context.user_data.get('markets', [])
    
    text = f"📊 <b>Markets</b>\n\nPage {page + 1}:"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=markets_keyboard(markets, page=page)
    )


async def custom_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom amount input."""
    try:
        amount = float(update.message.text.strip().replace('$', ''))
        
        if amount < Config.MIN_TRADE_USD:
            await update.message.reply_text(f"⚠️ Minimum amount is ${Config.MIN_TRADE_USD}")
            return CUSTOM_AMOUNT
        
        if amount > Config.MAX_TRADE_USD:
            await update.message.reply_text(f"⚠️ Maximum amount is ${Config.MAX_TRADE_USD}")
            return CUSTOM_AMOUNT
        
        token_id = context.user_data.get('selected_token_id')
        sub = context.user_data.get('selected_sub_market')
        event = context.user_data.get('selected_event')
        outcome = context.user_data.get('selected_outcome', 'YES')
        price = context.user_data.get('selected_price', 0.5)
        
        if not token_id:
            await update.message.reply_text("⚠️ Session expired. Use /buy to start over.")
            return ConversationHandler.END
        
        est_shares = amount / price if price > 0 else 0
        
        context.user_data['buy_amount'] = amount
        
        mode_text = "📝 PAPER" if Config.is_paper_mode() else "💱 LIVE"
        event_title = event.title if event else (sub.question if sub else 'Unknown')
        sub_title = sub.group_item_title or sub.question if sub else ''
        
        text = f"""
🚀 <b>Confirm Buy Order</b>

📋 <b>{event_title}</b>
🎯 <b>{sub_title}</b>

📍 <b>Outcome:</b> {outcome}
💵 <b>Price:</b> ${price:.4f}
💰 <b>Amount:</b> ${amount:.2f}
📦 <b>Est. Shares:</b> {est_shares:.2f}

<b>Mode:</b> {mode_text}
"""
        
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=buy_confirm_keyboard()
        )
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid number")
        return CUSTOM_AMOUNT
