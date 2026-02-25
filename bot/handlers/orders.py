"""
Orders Handlers

Telegram handlers for open orders and order book display.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.polymarket_client import get_polymarket_client


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /orders command - show all open orders."""
    client = get_polymarket_client()
    
    orders = await client.get_open_orders()
    
    if not orders:
        text = (
            "📭 <b>No Open Orders</b>\n\n"
            "You don't have any pending limit orders.\n"
            "Use /buy to place a new order."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode='HTML')
        else:
            await update.message.reply_text(text, parse_mode='HTML')
        return
    
    text = "📝 <b>Open Orders</b>\n\n"
    
    for i, order in enumerate(orders[:10], 1):
        side_emoji = "🟢" if order['side'].lower() == 'buy' else "🔴"
        filled_pct = (order['filled'] / order['size'] * 100) if order['size'] > 0 else 0
        
        text += f"{side_emoji} <b>{order['side'].upper()}</b> @ {order['price']*100:.0f}¢\n"
        text += f"   Size: {order['size']:.2f} | Filled: {filled_pct:.0f}%\n"
        text += f"   ID: <code>{order['order_id'][:12]}...</code>\n\n"
    
    # Create cancel buttons
    buttons = []
    for order in orders[:5]:
        buttons.append([
            InlineKeyboardButton(
                f"❌ Cancel {order['side'].upper()} @ {order['price']*100:.0f}¢",
                callback_data=f"cancel_{order['order_id'][:32]}"
            )
        ])
    
    if len(orders) > 0:
        buttons.append([
            InlineKeyboardButton("🗑️ Cancel All Orders", callback_data="cancel_all")
        ])
    
    buttons.append([
        InlineKeyboardButton("🔙 Menu", callback_data="menu")
    ])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(buttons)
        )


async def orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle orders button callback."""
    await update.callback_query.answer("📝 Loading orders...")
    await orders_command(update, context)


async def cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel order button."""
    query = update.callback_query
    await query.answer("⏳ Cancelling...")
    
    order_id = query.data.replace("cancel_", "")
    
    client = get_polymarket_client()
    success = await client.cancel_order(order_id)
    
    if success:
        await query.edit_message_text(
            f"✅ <b>Order Cancelled</b>\n\n"
            f"Order <code>{order_id[:16]}...</code> has been cancelled.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 View Orders", callback_data="orders"),
                InlineKeyboardButton("🏠 Menu", callback_data="menu")
            ]])
        )
    else:
        await query.edit_message_text(
            f"❌ <b>Cancel Failed</b>\n\n"
            f"Could not cancel order. It may have already been filled.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 View Orders", callback_data="orders"),
                InlineKeyboardButton("🏠 Menu", callback_data="menu")
            ]])
        )


async def cancel_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel all orders button."""
    query = update.callback_query
    await query.answer("⏳ Cancelling all orders...")
    
    client = get_polymarket_client()
    count = await client.cancel_all_orders()
    
    await query.edit_message_text(
        f"✅ <b>Orders Cancelled</b>\n\n"
        f"Cancelled {count} open order(s).",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Menu", callback_data="menu")
        ]])
    )


async def order_book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle order book display button."""
    query = update.callback_query
    await query.answer("📖 Loading order book...")
    
    # Get token_id from context
    token_id = context.user_data.get('selected_token_id')
    if not token_id:
        await query.edit_message_text(
            "❌ No token selected. Please select a market first.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Menu", callback_data="menu")
            ]])
        )
        return
    
    client = get_polymarket_client()
    book = await client.get_order_book(token_id)
    
    text = "📖 <b>Order Book</b>\n\n"
    
    # Display asks (sell orders) - top to bottom
    text += "🔴 <b>ASKS (Sell)</b>\n"
    for ask in reversed(book['asks'][:5]):
        price_cents = ask['price'] * 100
        text += f"   {price_cents:.0f}¢ | ${ask['size']:.2f}\n"
    
    # Spread
    if book['spread'] > 0:
        text += f"\n📊 Spread: {book['spread']*100:.1f}¢\n\n"
    else:
        text += "\n─────────────\n\n"
    
    # Display bids (buy orders) - top to bottom
    text += "🟢 <b>BIDS (Buy)</b>\n"
    for bid in book['bids'][:5]:
        price_cents = bid['price'] * 100
        text += f"   {price_cents:.0f}¢ | ${bid['size']:.2f}\n"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back", callback_data="back_out"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu")
        ]])
    )
