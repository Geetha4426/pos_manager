"""
Search Handlers

Handles /search and /info commands for finding markets.
"""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import Config
from core.polymarket_client import get_polymarket_client
from bot.keyboards.inline import search_results_keyboard, outcome_keyboard, search_prompt_keyboard


# Conversation states
SEARCH_INPUT = 0


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /search <query> command."""
    if not context.args:
        await update.message.reply_text(
            "🔍 <b>Search Markets</b>\n\n"
            "Usage: /search <query>\n\n"
            "Examples:\n"
            "• /search india cricket\n"
            "• /search lakers nba\n"
            "• /search trump election",
            parse_mode='HTML'
        )
        return
    
    query = ' '.join(context.args)
    
    await update.message.reply_text(f"🔍 Searching for: <b>{query}</b>...", parse_mode='HTML')
    
    client = get_polymarket_client()
    markets = await client.search_markets(query, limit=10)
    
    if not markets:
        await update.message.reply_text(
            f"📭 No markets found for '<b>{query}</b>'\n\n"
            "Try different keywords or /buy to browse categories.",
            parse_mode='HTML'
        )
        return
    
    context.user_data['markets'] = markets
    context.user_data['search_query'] = query
    
    # Build results text
    text = f"🔍 <b>Results for '{query}'</b>\n\n"
    
    for i, market in enumerate(markets[:8], 1):
        oe_yes = getattr(market, 'outcome_yes', 'Yes')
        oe_no = getattr(market, 'outcome_no', 'No')
        if oe_yes != 'Yes' and oe_no != 'No':
            yes_pct = int(market.yes_price * 100)
            no_pct = int(market.no_price * 100)
            text += f"{i}. {market.question[:45]}...\n"
            text += f"   🔵 {oe_yes}: {yes_pct}¢ | 🔴 {oe_no}: {no_pct}¢\n\n"
        else:
            yes_price = market.yes_price * 100
            text += f"{i}. {market.question[:45]}...\n"
            text += f"   ✅ YES: {yes_price:.0f}¢ | 📊 Vol: ${market.volume:,.0f}\n\n"
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=search_results_keyboard(markets)
    )


async def search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle search button callback - prompt for query and wait for text input."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔍 <b>Search Markets</b>\n\n"
        "Type your search query:\n\n"
        "Examples:\n"
        "• india cricket\n"
        "• nba playoffs\n"
        "• trump president\n\n"
        "<i>Send a message with your search term:</i>",
        parse_mode='HTML',
        reply_markup=search_prompt_keyboard()
    )
    
    return SEARCH_INPUT


async def search_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input after search button - perform the search."""
    query = update.message.text.strip()
    
    if not query:
        await update.message.reply_text("⚠️ Please enter a search term")
        return SEARCH_INPUT
    
    await update.message.reply_text(f"🔍 Searching for: <b>{query}</b>...", parse_mode='HTML')
    
    client = get_polymarket_client()
    markets = await client.search_markets(query, limit=10)
    
    if not markets:
        await update.message.reply_text(
            f"📭 No markets found for '<b>{query}</b>'\n\n"
            "Try different keywords or /buy to browse categories.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    context.user_data['markets'] = markets
    context.user_data['search_query'] = query
    
    # Build results text
    text = f"🔍 <b>Results for '{query}'</b>\n\n"
    
    for i, market in enumerate(markets[:8], 1):
        oe_yes = getattr(market, 'outcome_yes', 'Yes')
        oe_no = getattr(market, 'outcome_no', 'No')
        if oe_yes != 'Yes' and oe_no != 'No':
            yes_pct = int(market.yes_price * 100)
            no_pct = int(market.no_price * 100)
            text += f"{i}. {market.question[:45]}...\n"
            text += f"   🔵 {oe_yes}: {yes_pct}¢ | 🔴 {oe_no}: {no_pct}¢\n\n"
        else:
            yes_price = market.yes_price * 100
            text += f"{i}. {market.question[:45]}...\n"
            text += f"   ✅ YES: {yes_price:.0f}¢ | 📊 Vol: ${market.volume:,.0f}\n\n"
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=search_results_keyboard(markets)
    )
    
    return ConversationHandler.END


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /info <query> command - detailed market info."""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ <b>Market Info</b>\n\n"
            "Usage: /info <query>\n\n"
            "Shows detailed info for a market.",
            parse_mode='HTML'
        )
        return
    
    query = ' '.join(context.args)
    
    client = get_polymarket_client()
    markets = await client.search_markets(query, limit=1)
    
    if not markets:
        await update.message.reply_text(f"📭 No market found for '{query}'")
        return
    
    market = markets[0]
    context.user_data['selected_market'] = market
    
    # Get actual outcome labels
    oe_yes = getattr(market, 'outcome_yes', 'Yes')
    oe_no = getattr(market, 'outcome_no', 'No')
    
    yes_prob = market.yes_price * 100
    no_prob = market.no_price * 100
    
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

📋 <b>{market.question}</b>

💹 <b>Prices:</b>
{price_text}

📈 <b>Volume:</b> ${market.volume:,.0f}
🏷️ <b>Category:</b> {market.category}

<b>Buy this market:</b>
"""
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard(outcome_yes=oe_yes, outcome_no=oe_no)
    )


async def hot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /hot command - show trending markets."""
    try:
        client = get_polymarket_client()
        
        # Get sports markets sorted by volume
        markets = await client.get_sports_markets(limit=10)
        
        if not markets:
            markets = await client.search_markets("", limit=10)
    except Exception as e:
        text = f"\u26a0\ufe0f Could not fetch trending markets.\n\n<i>Error: {str(e)[:100]}</i>"
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode='HTML')
        else:
            await update.message.reply_text(text, parse_mode='HTML')
        return
    
    if not markets:
        text = "📭 No trending markets found"
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return
    
    # Sort by volume
    markets.sort(key=lambda m: m.volume, reverse=True)
    context.user_data['markets'] = markets
    
    text = "🔥 <b>Trending Markets</b>\n\n"
    
    for i, market in enumerate(markets[:8], 1):
        emoji = Config.get_sport_emoji(market.category)
        text += f"{emoji} {market.question[:40]}...\n"
        text += f"   💰 ${market.volume:,.0f} | ✅ {market.yes_price*100:.0f}¢\n\n"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=search_results_keyboard(markets)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=search_results_keyboard(markets)
        )


async def hot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle hot button callback."""
    await update.callback_query.answer("🔥 Loading trending...")
    await hot_command(update, context)
