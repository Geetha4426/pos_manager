"""
Favorites Handlers

Handles favorites management commands.
Uses index-based callbacks with context storage.
"""

from telegram import Update
from telegram.ext import ContextTypes

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.polymarket_client import get_polymarket_client, SubMarket
from core.favorites_db import get_favorites_db
from bot.keyboards.inline import favorites_keyboard, outcome_keyboard


async def favorites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /favorites command - list saved markets."""
    user_id = str(update.effective_user.id)
    
    db = await get_favorites_db()
    favorites = await db.get_favorites(user_id)
    
    # Store for callback reference
    context.user_data['favorites'] = favorites
    
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
    
    user_id = str(update.effective_user.id)
    
    # Get market info from context
    market = context.user_data.get('selected_market')
    outcome = context.user_data.get('selected_outcome', 'Yes')
    
    if not market:
        await query.answer("⚠️ No market selected", show_alert=True)
        return
    
    label = market.question[:50] if market else "Unknown"
    token_id = market.yes_token_id if outcome == 'YES' else market.no_token_id
    
    db = await get_favorites_db()
    success = await db.add_favorite(
        user_id=user_id,
        market_id=market.condition_id,
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
    
    # Get index from callback: fv_0 -> 0
    idx = int(query.data.split('_')[1])
    favorites = context.user_data.get('favorites', [])
    
    if idx >= len(favorites):
        await query.edit_message_text("⚠️ Favorite not found")
        return
    
    fav = favorites[idx]
    
    client = get_polymarket_client()
    market = await client.get_market_details(fav.market_id)
    
    if not market:
        await query.edit_message_text(
            "⚠️ Market not found. It may have been resolved or removed from Polymarket."
        )
        return
    
    # Build a SubMarket so the buy flow works (outcome_callback expects selected_sub_market)
    sub = SubMarket(
        condition_id=market.condition_id,
        question=market.question,
        yes_token_id=market.yes_token_id,
        no_token_id=market.no_token_id,
        yes_price=market.yes_price,
        no_price=market.no_price,
        group_item_title=market.question[:60],
        outcome_yes=market.outcome_yes,
        outcome_no=market.outcome_no,
    )
    context.user_data['selected_sub_market'] = sub
    context.user_data['selected_market'] = sub  # Legacy compat
    context.user_data['selected_event'] = None  # No parent event
    
    # Refresh prices from CLOB
    yes_price = market.yes_price
    no_price = market.no_price
    try:
        if market.yes_token_id:
            live_yes = await client.get_price(market.yes_token_id)
            if live_yes > 0 and live_yes != 0.5:
                yes_price = live_yes
                sub.yes_price = live_yes
        if market.no_token_id:
            live_no = await client.get_price(market.no_token_id)
            if live_no > 0 and live_no != 0.5:
                no_price = live_no
                sub.no_price = live_no
    except Exception:
        pass
    
    oe_yes = market.outcome_yes
    oe_no = market.outcome_no
    yes_prob = yes_price * 100
    no_prob = no_price * 100
    
    if oe_yes != 'Yes' and oe_no != 'No':
        price_text = (
            f"   🔵 {oe_yes}: {yes_prob:.0f}¢ (${yes_price:.2f})\n"
            f"   🔴 {oe_no}: {no_prob:.0f}¢ (${no_price:.2f})"
        )
    else:
        price_text = (
            f"   ✅ YES: {yes_prob:.0f}¢ (${yes_price:.2f})\n"
            f"   ❌ NO: {no_prob:.0f}¢ (${no_price:.2f})"
        )
    
    text = (
        f"⭐ <b>Favorite Market</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>{market.question}</b>\n\n"
        f"💹 <b>Prices:</b>\n"
        f"{price_text}\n"
        f"📈 <b>Volume:</b> ${market.volume:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Select your position:</b>"
    )
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=outcome_keyboard(outcome_yes=oe_yes, outcome_no=oe_no)
    )


async def fav_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete favorite callback."""
    query = update.callback_query
    
    # Get index from callback: fd_0 -> 0
    idx = int(query.data.split('_')[1])
    favorites = context.user_data.get('favorites', [])
    
    if idx >= len(favorites):
        await query.answer("⚠️ Not found", show_alert=True)
        return
    
    fav = favorites[idx]
    user_id = str(update.effective_user.id)
    
    db = await get_favorites_db()
    await db.remove_favorite(user_id, fav.market_id, fav.outcome)
    await query.answer("🗑️ Removed from favorites", show_alert=True)
    
    # Refresh list
    await favorites_command(update, context)
