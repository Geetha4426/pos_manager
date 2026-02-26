"""
Trading Handlers

Handles /buy command with EVENT-based sports navigation.
Shows: Sport → Events (matches) → Sub-Markets (toss, top scorer, etc.) → Yes/No
Events sorted: 🔴 LIVE first → 🟢 Upcoming by date. Past events excluded.
"""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import Config
from core.polymarket_client import get_polymarket_client, require_auth, event_status
from bot.keyboards.inline import (
    category_keyboard, sports_keyboard, leagues_keyboard, events_keyboard,
    sub_markets_keyboard, outcome_keyboard, amount_keyboard,
    buy_confirm_keyboard, markets_keyboard
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
    """Handle sport selection - fetch LEAGUES first, then events."""
    query = update.callback_query
    await query.answer("🔍 Loading leagues...")
    
    sport = query.data.split('_')[1]  # sp_cricket -> cricket
    context.user_data['sport'] = sport
    
    sport_emoji = Config.get_sport_emoji(sport)
    client = get_polymarket_client()
    
    # Try to fetch leagues/series for this sport
    leagues = await client.get_sports_leagues(sport)
    context.user_data['leagues'] = leagues
    
    if leagues:
        # Show league selection
        text = f"""
{sport_emoji} <b>{sport.upper()} Leagues</b>

Found {len(leagues)} leagues/tournaments:

<i>Select a league to see matches, or view all events:</i>
"""
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=leagues_keyboard(leagues, sport)
        )
    else:
        # No leagues found (e.g., UFC uses tags) — fall back to all events
        events = await client.get_sports_events(sport=sport, limit=15)
        context.user_data['events'] = events
        
        if not events:
            await query.edit_message_text(
                f"📭 No active {sport.upper()} events found.\n\nTry /search {sport}",
                reply_markup=sports_keyboard()
            )
            return
        
        # Count live vs upcoming
        live_count = sum(1 for e in events if event_status(e.start_date, e.end_date) == 'live')
        upcoming_count = len(events) - live_count
        status_line = ""
        if live_count:
            status_line += f"🔴 {live_count} live  "
        if upcoming_count:
            status_line += f"🟢 {upcoming_count} upcoming"
        
        text = f"""
{sport_emoji} <b>{sport.upper()} Events</b>

Found {len(events)} active matches/events:
{status_line}

<i>Tap an event to see betting options</i>
"""
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=events_keyboard(events)
        )


async def league_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle league selection - fetch events for the selected league."""
    query = update.callback_query
    await query.answer("🔍 Loading events...")
    
    sport = context.user_data.get('sport', 'sports')
    sport_emoji = Config.get_sport_emoji(sport)
    client = get_polymarket_client()
    
    league_data = query.data  # lg_0, lg_1, or lg_all
    league_key = league_data.split('_')[1]
    
    if league_key == 'all':
        # "All Events" — fetch without league filter
        events = await client.get_sports_events(sport=sport, limit=15)
        league_name = f"All {sport.upper()}"
    else:
        # Fetch events for specific league
        idx = int(league_key)
        leagues = context.user_data.get('leagues', [])
        
        if idx >= len(leagues):
            await query.edit_message_text("⚠️ League not found. Try again with /buy")
            return
        
        league = leagues[idx]
        league_name = league.name
        events = await client.get_events_by_league(
            series_id=league.series_id,
            sport=sport,
            limit=15
        )
    
    context.user_data['events'] = events
    context.user_data['selected_league_name'] = league_name
    
    if not events:
        await query.edit_message_text(
            f"📭 No active events in <b>{league_name}</b>.\n\nTry another league or /search {sport}",
            parse_mode='HTML',
            reply_markup=leagues_keyboard(context.user_data.get('leagues', []), sport)
        )
        return
    
    # Count live vs upcoming
    live_count = sum(1 for e in events if event_status(e.start_date, e.end_date) == 'live')
    upcoming_count = len(events) - live_count
    status_line = ""
    if live_count:
        status_line += f"🔴 {live_count} live  "
    if upcoming_count:
        status_line += f"🟢 {upcoming_count} upcoming"
    
    text = f"""
{sport_emoji} <b>{league_name}</b>

Found {len(events)} active matches:
{status_line}

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
    
    # Build timing badge
    st = event_status(event.start_date, event.end_date)
    if st == 'live':
        timing = "🔴 <b>LIVE</b>"
    elif st == 'upcoming':
        timing = "🟢 Upcoming"
        from core.polymarket_client import parse_event_date
        dt = parse_event_date(event.start_date)
        if dt:
            timing += f" — {dt.strftime('%d %b %H:%M')} UTC"
    else:
        timing = ""
    
    text = f"""
📊 <b>{event.title}</b>
{timing}

<b>Available Betting Options ({len(sub_markets)}):</b>

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
    
    # Get actual outcome labels (team names or Yes/No)
    oe_yes = getattr(sub, 'outcome_yes', 'Yes')
    oe_no = getattr(sub, 'outcome_no', 'No')
    
    # Calculate implied probabilities
    yes_prob = sub.yes_price * 100
    no_prob = sub.no_price * 100
    
    # Use team names or Yes/No in display
    if oe_yes != 'Yes' and oe_no != 'No':
        price_text = (
            f"   🔵 {oe_yes}: {yes_prob:.0f}¢ (${sub.yes_price:.2f})\n"
            f"   🔴 {oe_no}: {no_prob:.0f}¢ (${sub.no_price:.2f})"
        )
    else:
        price_text = (
            f"   ✅ YES: {yes_prob:.0f}¢ (${sub.yes_price:.2f})\n"
            f"   ❌ NO: {no_prob:.0f}¢ (${sub.no_price:.2f})"
        )
    
    text = f"""
📊 <b>Market Details</b>

📋 <b>{event.title}</b>
🎯 <b>{sub.group_item_title or sub.question}</b>

💹 <b>Prices:</b>
{price_text}

<b>Select your position:</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard(outcome_yes=oe_yes, outcome_no=oe_no)
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
    
    outcome_key = query.data.split('_')[1].upper()  # out_yes -> YES
    
    sub = context.user_data.get('selected_sub_market')
    if not sub:
        await query.edit_message_text("⚠️ Market not found. Start over with /buy")
        return
    
    # Get actual outcome labels
    oe_yes = getattr(sub, 'outcome_yes', 'Yes')
    oe_no = getattr(sub, 'outcome_no', 'No')
    
    # Get the correct token and price
    if outcome_key == 'YES':
        token_id = sub.yes_token_id
        price = sub.yes_price
        outcome_label = oe_yes  # e.g., "India" or "Yes"
    else:
        token_id = sub.no_token_id
        price = sub.no_price
        outcome_label = oe_no  # e.g., "Pakistan" or "No"
    
    if not token_id:
        await query.edit_message_text("⚠️ Token data unavailable for this market. Try another market.")
        return
    
    # Refresh price from CLOB for accuracy (Gamma prices can be stale)
    try:
        client = get_polymarket_client()
        live_price = await client.get_price(token_id)
        if live_price > 0 and live_price != 0.5:
            price = live_price
    except Exception:
        pass  # Keep Gamma price as fallback
    
    context.user_data['selected_token_id'] = token_id
    context.user_data['selected_outcome'] = outcome_label  # Store actual label
    context.user_data['selected_price'] = price
    
    event = context.user_data.get('selected_event')
    event_title = event.title if event else sub.question
    
    text = f"""
💵 <b>Enter Amount</b>

📋 {event_title}
🎯 <b>{sub.group_item_title or sub.question}</b>
📍 <b>Buying:</b> {outcome_label} @ ${price:.2f}

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
    
    oe_yes = getattr(sub, 'outcome_yes', 'Yes')
    oe_no = getattr(sub, 'outcome_no', 'No')
    yes_prob = sub.yes_price * 100
    no_prob = sub.no_price * 100
    
    event_title = event.title if event else sub.question
    
    if oe_yes != 'Yes' and oe_no != 'No':
        price_text = (
            f"   🔵 {oe_yes}: {yes_prob:.0f}¢\n"
            f"   🔴 {oe_no}: {no_prob:.0f}¢"
        )
    else:
        price_text = (
            f"   ✅ YES: {yes_prob:.0f}¢\n"
            f"   ❌ NO: {no_prob:.0f}¢"
        )
    
    text = f"""
📊 <b>Market Details</b>

📋 <b>{event_title}</b>
🎯 <b>{sub.group_item_title or sub.question}</b>

💹 <b>Prices:</b>
{price_text}

<b>Select your position:</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard(outcome_yes=oe_yes, outcome_no=oe_no)
    )


async def amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount selection - show confirmation."""
    query = update.callback_query
    await query.answer()
    
    amount_str = query.data.split('_')[1]  # amt_10 -> 10
    
    if amount_str == 'custom':  # custom
        await query.edit_message_text(
            f"✏️ <b>Custom Amount</b>\n\nEnter amount in USD (min ${Config.MIN_TRADE_USD:.0f}, max ${Config.MAX_TRADE_USD:.0f}):",
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
    
    client = await require_auth(update)
    if not client:
        return
    result = await client.buy_market(token_id, amount, market_info=market_info)
    
    if result.success:
        event_title = event.title if event else (sub.question if sub else 'Position')
        sub_title = sub.group_item_title or sub.question if sub else ''
        
        # Add to position manager for live tracking
        try:
            from core.position_manager import get_position_manager
            pm = get_position_manager()
            await pm.add_position(
                token_id=token_id,
                condition_id=sub.condition_id if sub else '',
                question=event_title,
                outcome=outcome,
                size=result.filled_size if result.filled_size > 0 else amount / (result.avg_price if result.avg_price > 0 else 0.5),
                avg_price=result.avg_price if result.avg_price > 0 else 0.5,
                current_price=result.avg_price if result.avg_price > 0 else 0.5,
            )
        except Exception:
            pass
        
        text = (
            f"✅ <b>Buy Executed!</b>\n\n"
            f"📋 {event_title}\n"
            f"🎯 {sub_title}\n"
            f"📍 <b>Outcome:</b> {outcome}\n\n"
            f"📦 <b>Shares:</b> {result.filled_size:.2f}\n"
            f"💵 <b>Avg Price:</b> {result.avg_price*100:.1f}¢\n"
            f"🆔 <code>{result.order_id[:16]}...</code>\n\n"
            f"{'📝 Paper trade' if Config.is_paper_mode() else '💱 Live trade'}\n\n"
            f"Use /positions to view (live P&L) ⚡"
        )
    else:
        error_msg = result.error or 'Unknown error'
        # Detect geo-block for user-friendly message
        from core.polymarket_client import is_geo_block_error
        if is_geo_block_error(error_msg):
            text = (
                "🚫 <b>Trading Blocked (Geo-Restriction)</b>\n\n"
                "Polymarket restricts trading from certain regions.\n"
                "Your server IP is in a blocked region.\n\n"
                "🌍 <b>Blocked:</b> US, Cuba, Iran, North Korea, Syria, "
                "Russia, Belarus, Myanmar, Venezuela, Zimbabwe, France\n\n"
                "💡 Deploy on a server in an allowed region."
            )
        elif 'invalid signature' in error_msg.lower():
            # Show per-user sig_type (from /connect session), NOT the env var
            per_user_sig = '?'
            per_user_funder = '?'
            try:
                cc = client.clob_client if client else None
                if cc:
                    bld = getattr(cc, 'builder', None)
                    per_user_sig = getattr(bld, 'sig_type', '?') if bld else '?'
                    per_user_funder = getattr(bld, 'funder', '?') if bld else '?'
            except Exception:
                pass
            sig_label = {0: 'EOA', 1: 'Proxy/Magic', 2: 'GnosisSafe'}.get(per_user_sig, str(per_user_sig))
            text = (
                "❌ <b>Invalid Signature</b>\n\n"
                "The order was rejected because the signature doesn't match.\n\n"
                f"<b>Your session config:</b>\n"
                f"• sig_type: {per_user_sig} ({sig_label})\n"
                f"• funder: <code>{str(per_user_funder)[:16]}...</code>\n\n"
                "<b>Fix:</b>\n"
                "• /disconnect → /connect again with correct wallet type\n"
                "• Email/browser login → provide funder address (sig_type=1)\n"
                "• MetaMask/EOA → skip funder (sig_type=0)\n\n"
                "Use /debug_wallet for full config info."
            )
        else:
            text = f"""
❌ <b>Buy Failed</b>

Error: {error_msg}

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
    
    # Get actual outcome labels
    oe_yes = getattr(market, 'outcome_yes', 'Yes')
    oe_no = getattr(market, 'outcome_no', 'No')
    
    # Convert to sub-market for compatibility
    from core.polymarket_client import SubMarket
    sub = SubMarket(
        condition_id=market.condition_id,
        question=market.question,
        yes_token_id=market.yes_token_id,
        no_token_id=market.no_token_id,
        yes_price=market.yes_price,
        no_price=market.no_price,
        group_item_title='',
        outcome_yes=oe_yes,
        outcome_no=oe_no
    )
    
    context.user_data['selected_sub_market'] = sub
    context.user_data['selected_market'] = market
    context.user_data['selected_event'] = None  # No parent event
    
    yes_prob = market.yes_price * 100
    no_prob = market.no_price * 100
    
    if oe_yes != 'Yes' and oe_no != 'No':
        price_text = (
            f"   🔵 {oe_yes}: {yes_prob:.0f}¢ (${market.yes_price:.2f})\n"
            f"   🔴 {oe_no}: {no_prob:.0f}¢ (${market.no_price:.2f})"
        )
    else:
        price_text = (
            f"   ✅ YES: {yes_prob:.0f}¢ (${market.yes_price:.2f})\n"
            f"   ❌ NO: {no_prob:.0f}¢ (${market.no_price:.2f})"
        )
    
    text = f"""
📊 <b>Market Details</b>

📋 <b>{market.question}</b>

💹 <b>Prices:</b>
{price_text}

📈 <b>Volume:</b> ${market.volume:,.0f}

<b>Select your position:</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard(outcome_yes=oe_yes, outcome_no=oe_no)
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
            # Try to recover from sub-market data
            if sub:
                if outcome == 'YES':
                    token_id = getattr(sub, 'yes_token_id', None)
                else:
                    token_id = getattr(sub, 'no_token_id', None)
                if token_id:
                    context.user_data['selected_token_id'] = token_id
            
            if not token_id:
                await update.message.reply_text("⚠️ Market data not found. Use /buy to start over.")
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
