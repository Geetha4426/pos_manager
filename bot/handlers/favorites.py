"""
Favorites Handlers

Handles favorites management commands.
"""

from telegram import Update
from telegram.ext import ContextTypes

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.polymarket_client import get_polymarket_client
from core.favorites_db import get_favorites_db
from bot.keyboards.inline import favorites_keyboard, outcome_keyboard


async def favorites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /favorites command - list saved markets."""
    user_id = str(update.effective_user.id)
    
    db = await get_favorites_db()
    favorites = await db.get_favorites(user_id)
    
    if not favorites:
        text = """
⭐ <b>Favorites</b>

<i>No favorites saved yet.</i>

Add favorites from search results or market details.
"""
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode='HTML')
        else:
            await update.message.reply_text(text, parse_mode='HTML')
        return
    
    text = f"⭐ <b>Your Favorites ({len(favorites)})</b>\n\n"
    text += "<i>Tap to view or trade:</i>\n"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=favorites_keyboard(favorites)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=favorites_keyboard(favorites)
        )


async def favorites_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle favorites button callback."""
    await update.callback_query.answer()
    await favorites_command(update, context)


async def fav_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle add to favorites callback."""
    query = update.callback_query
    await query.answer("⭐ Added to favorites!")
    
    token_id = query.data.split('_')[2]  # fav_add_{token_id}
    user_id = str(update.effective_user.id)
    
    # Get market info from context
    market = context.user_data.get('selected_market')
    outcome = context.user_data.get('selected_outcome', 'Yes')
    
    label = market.question[:50] if market else f"Market {token_id[:8]}"
    condition_id = market.condition_id if market else token_id
    
    db = await get_favorites_db()
    success = await db.add_favorite(
        user_id=user_id,
        market_id=condition_id,
        token_id=token_id,
        label=label,
        outcome=outcome
    )
    
    if success:
        await query.answer("⭐ Added to favorites!", show_alert=True)
    else:
        await query.answer("⚠️ Already in favorites", show_alert=True)


async def fav_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle view favorite callback - show market details."""
    query = update.callback_query
    await query.answer("📊 Loading market...")
    
    market_id = query.data.split('_')[2]  # fav_view_{market_id}
    
    client = get_polymarket_client()
    market = await client.get_market_details(market_id)
    
    if not market:
        await query.edit_message_text("⚠️ Market not found or closed")
        return
    
    context.user_data['selected_market'] = market
    
    yes_prob = market.yes_price * 100
    no_prob = market.no_price * 100
    
    text = f"""
⭐ <b>Favorite Market</b>

📋 <b>{market.question}</b>

💹 <b>Prices:</b>
   ✅ YES: {yes_prob:.0f}¢
   ❌ NO: {no_prob:.0f}¢

📈 <b>Volume:</b> ${market.volume:,.0f}

<b>Buy this market:</b>
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard(market.condition_id, market.yes_price, market.no_price)
    )


async def fav_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete favorite callback."""
    query = update.callback_query
    
    fav_id = query.data.split('_')[2]  # fav_del_{id}
    user_id = str(update.effective_user.id)
    
    db = await get_favorites_db()
    
    # Get favorite to find market_id
    favorites = await db.get_favorites(user_id)
    fav = next((f for f in favorites if str(f.id) == fav_id), None)
    
    if fav:
        await db.remove_favorite(user_id, fav.market_id, fav.outcome)
        await query.answer("🗑️ Removed from favorites", show_alert=True)
    else:
        await query.answer("⚠️ Not found", show_alert=True)
    
    # Refresh list
    await favorites_command(update, context)
