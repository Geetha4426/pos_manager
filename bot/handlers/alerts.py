"""
Alerts Handlers

Telegram handlers for price alerts, stop-loss, and take-profit orders.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.alerts import get_alert_manager, AlertType
from core.polymarket_client import get_polymarket_client


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts command - show all active alerts."""
    user_id = str(update.effective_user.id)
    manager = get_alert_manager()
    
    alerts = await manager.get_alerts(user_id=user_id, active_only=True)
    
    if not alerts:
        await update.message.reply_text(
            "🔔 <b>No Active Alerts</b>\n\n"
            "You don't have any price alerts set.\n\n"
            "<b>Commands:</b>\n"
            "• /alert <i>market price</i> - Set price alert\n"
            "• /stoploss <i>position price</i> - Set stop-loss\n"
            "• /takeprofit <i>position price</i> - Set take-profit\n",
            parse_mode='HTML'
        )
        return
    
    text = "🔔 <b>Active Alerts</b>\n\n"
    
    buttons = []
    for alert in alerts[:8]:
        type_emoji = {
            AlertType.PRICE_ALERT: "📢",
            AlertType.STOP_LOSS: "🛑",
            AlertType.TAKE_PROFIT: "🎯"
        }.get(alert.alert_type, "🔔")
        
        direction = "⬆️" if alert.side == "above" else "⬇️"
        
        text += f"{type_emoji} {alert.market_question[:35]}...\n"
        text += f"   {direction} Trigger: {alert.trigger_price*100:.0f}¢\n"
        if alert.auto_trade:
            text += f"   ⚡ Auto-trade: ${alert.trade_amount:.2f}\n"
        text += "\n"
        
        buttons.append([
            InlineKeyboardButton(
                f"❌ Remove ({alert.trigger_price*100:.0f}¢)",
                callback_data=f"del_alert_{alert.id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alert command - set a price alert."""
    user_id = str(update.effective_user.id)
    
    # Parse args: /alert <market> <price>
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "📢 <b>Set Price Alert</b>\n\n"
            "Usage: /alert <i>market_keyword</i> <i>price</i>\n\n"
            "Examples:\n"
            "• /alert cricket 65 - Alert when cricket market hits 65¢\n"
            "• /alert trump 45 - Alert when Trump market hits 45¢",
            parse_mode='HTML'
        )
        return
    
    price_arg = context.args[-1]
    market_query = ' '.join(context.args[:-1])
    
    try:
        trigger_price = float(price_arg) / 100  # Convert cents to decimal
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Use format: /alert market 65")
        return
    
    if trigger_price < 0.01 or trigger_price > 0.99:
        await update.message.reply_text("❌ Price must be between 1¢ and 99¢")
        return
    
    # Search for market
    client = get_polymarket_client()
    markets = await client.search_markets(market_query, limit=1)
    
    if not markets:
        await update.message.reply_text(f"❌ No markets found for: {market_query}")
        return
    
    market = markets[0]
    current_price = market.yes_price
    side = "above" if trigger_price > current_price else "below"
    
    manager = get_alert_manager()
    alert_id = await manager.add_alert(
        user_id=user_id,
        token_id=market.yes_token_id,
        market_question=market.question,
        alert_type=AlertType.PRICE_ALERT,
        trigger_price=trigger_price,
        side=side
    )
    
    await update.message.reply_text(
        f"✅ <b>Alert Set!</b>\n\n"
        f"📊 {market.question[:50]}...\n"
        f"🔔 Trigger: {trigger_price*100:.0f}¢ ({side})\n"
        f"📍 Current: {current_price*100:.0f}¢\n\n"
        f"You'll be notified when the price crosses {trigger_price*100:.0f}¢",
        parse_mode='HTML'
    )


async def stoploss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stoploss command - set a stop-loss."""
    user_id = str(update.effective_user.id)
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "🛑 <b>Set Stop-Loss</b>\n\n"
            "Usage: /stoploss <i>position_id</i> <i>price</i>\n\n"
            "This will automatically sell when price drops below the threshold.",
            parse_mode='HTML'
        )
        return
    
    # For simplicity, use market search like /alert
    price_arg = context.args[-1]
    market_query = ' '.join(context.args[:-1])
    
    try:
        stop_price = float(price_arg) / 100
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Use format: /stoploss market 30")
        return
    
    client = get_polymarket_client()
    markets = await client.search_markets(market_query, limit=1)
    
    if not markets:
        await update.message.reply_text(f"❌ No markets found for: {market_query}")
        return
    
    market = markets[0]
    
    manager = get_alert_manager()
    await manager.add_stop_loss(
        user_id=user_id,
        token_id=market.yes_token_id,
        market_question=market.question,
        stop_price=stop_price
    )
    
    await update.message.reply_text(
        f"🛑 <b>Stop-Loss Set!</b>\n\n"
        f"📊 {market.question[:50]}...\n"
        f"⬇️ Trigger: {stop_price*100:.0f}¢\n"
        f"⚡ Auto-sell when price drops below threshold",
        parse_mode='HTML'
    )


async def takeprofit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /takeprofit command - set a take-profit."""
    user_id = str(update.effective_user.id)
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "🎯 <b>Set Take-Profit</b>\n\n"
            "Usage: /takeprofit <i>position_id</i> <i>price</i>\n\n"
            "This will automatically sell when price rises above the threshold.",
            parse_mode='HTML'
        )
        return
    
    price_arg = context.args[-1]
    market_query = ' '.join(context.args[:-1])
    
    try:
        target_price = float(price_arg) / 100
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Use format: /takeprofit market 80")
        return
    
    client = get_polymarket_client()
    markets = await client.search_markets(market_query, limit=1)
    
    if not markets:
        await update.message.reply_text(f"❌ No markets found for: {market_query}")
        return
    
    market = markets[0]
    
    manager = get_alert_manager()
    await manager.add_take_profit(
        user_id=user_id,
        token_id=market.yes_token_id,
        market_question=market.question,
        target_price=target_price
    )
    
    await update.message.reply_text(
        f"🎯 <b>Take-Profit Set!</b>\n\n"
        f"📊 {market.question[:50]}...\n"
        f"⬆️ Trigger: {target_price*100:.0f}¢\n"
        f"⚡ Auto-sell when price rises above threshold",
        parse_mode='HTML'
    )


async def delete_alert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete alert button."""
    query = update.callback_query
    await query.answer("🗑️ Removing alert...")
    
    alert_id = int(query.data.replace("del_alert_", ""))
    
    manager = get_alert_manager()
    await manager.remove_alert(alert_id)
    
    await query.edit_message_text(
        "✅ Alert removed successfully.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔔 View Alerts", callback_data="alerts"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu")
        ]])
    )


async def alerts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle alerts button callback."""
    await update.callback_query.answer("🔔 Loading alerts...")
    await alerts_command(update, context)
